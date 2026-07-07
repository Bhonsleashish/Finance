"""Rule-based transaction categorizer with learning from manual corrections.

Resolution order for a transaction description:
  1. Exact/substring match against known merchant patterns (DB-backed,
     seeded from config/merchants.yaml + anything learned from corrections).
  2. Fuzzy match against merchant names (rapidfuzz) to catch OCR noise/typos.
  3. Keyword match against config/categories.yaml category keywords.
  4. Fall back to "Miscellaneous" and flag for review.

Whenever a user corrects a transaction's category (db.repository.
correct_transaction_category), the merchant text is normalized and stored as
a new learned merchant pattern so the *next* transaction from the same
merchant is categorized correctly automatically — this is the "learning"
loop, no ML model, no network calls needed.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from finance_os.config import load_categories
from finance_os.db import repository as repo

FUZZY_MATCH_THRESHOLD = 88
FALLBACK_CATEGORY = "Miscellaneous"


@dataclass
class CategorizationResult:
    merchant_id: int | None
    merchant_name: str | None
    category_id: int | None
    category_name: str | None
    confidence: str  # 'merchant_exact' | 'merchant_fuzzy' | 'keyword' | 'fallback'


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class Categorizer:
    """Holds an in-memory index of merchant patterns for fast repeated lookups
    within one ingestion run; call `refresh()` after learning new patterns.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.refresh()

    def refresh(self) -> None:
        self._patterns = repo.all_merchant_patterns(self.conn)
        self._merchant_names = {
            row["merchant_id"]: row["merchant_name"] for row in self._patterns
        }
        # Also index merchants with no explicit pattern (match on name itself)
        all_merchants = self.conn.execute("SELECT id, name, default_category_id FROM merchants").fetchall()
        for m in all_merchants:
            self._merchant_names.setdefault(m["id"], m["name"])
        self._categories = load_categories()

    def categorize(self, description: str) -> CategorizationResult:
        norm = _normalize(description)

        # 1. exact/substring pattern match
        for row in self._patterns:
            if row["pattern"] and row["pattern"] in norm:
                return CategorizationResult(
                    merchant_id=row["merchant_id"],
                    merchant_name=row["merchant_name"],
                    category_id=row["category_id"],
                    category_name=self._category_name(row["category_id"]),
                    confidence="merchant_exact",
                )

        # 2. fuzzy match against merchant names (handles OCR noise / typos)
        if self._merchant_names:
            choices = list(self._merchant_names.values())
            best = process.extractOne(norm, choices, scorer=fuzz.partial_ratio)
            if best and best[1] >= FUZZY_MATCH_THRESHOLD:
                matched_name = best[0]
                merchant_id = next(mid for mid, name in self._merchant_names.items() if name == matched_name)
                row = self.conn.execute(
                    "SELECT default_category_id FROM merchants WHERE id = ?", (merchant_id,)
                ).fetchone()
                category_id = row["default_category_id"] if row else None
                return CategorizationResult(
                    merchant_id=merchant_id,
                    merchant_name=matched_name,
                    category_id=category_id,
                    category_name=self._category_name(category_id),
                    confidence="merchant_fuzzy",
                )

        # 3. keyword match against category definitions
        for category_name, meta in self._categories.items():
            keywords = meta.get("keywords", []) if isinstance(meta, dict) else []
            for kw in keywords:
                if kw and kw.lower() in norm:
                    category_id = repo.get_category_id(self.conn, category_name)
                    return CategorizationResult(
                        merchant_id=None,
                        merchant_name=None,
                        category_id=category_id,
                        category_name=category_name,
                        confidence="keyword",
                    )

        # 4. fallback
        category_id = repo.get_category_id(self.conn, FALLBACK_CATEGORY)
        return CategorizationResult(
            merchant_id=None,
            merchant_name=None,
            category_id=category_id,
            category_name=FALLBACK_CATEGORY,
            confidence="fallback",
        )

    def _category_name(self, category_id: int | None) -> str | None:
        if category_id is None:
            return None
        row = self.conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
        return row["name"] if row else None

    def learn_correction(self, transaction_id: int, description: str, new_category_name: str) -> None:
        """User corrected a transaction's category: create/extend a learned
        merchant so future transactions from this merchant text auto-categorize.
        """
        category_id = repo.get_or_create_category(self.conn, new_category_name)
        norm = _normalize(description)
        # Use a short, stable token from the description as the merchant key
        # (first alphabetic word run of length >= 3) to avoid over-fitting to
        # one-off strings like transaction IDs.
        token_match = re.search(r"[a-zäöüß]{3,}", norm)
        merchant_key = token_match.group(0) if token_match else norm[:30]

        merchant_id = repo.get_or_create_merchant(self.conn, merchant_key, category_id, is_learned=True)
        # Keep the merchant's default category current even if it already existed.
        self.conn.execute(
            "UPDATE merchants SET default_category_id = ? WHERE id = ?", (category_id, merchant_id)
        )
        repo.add_merchant_pattern(self.conn, merchant_id, merchant_key)
        repo.correct_transaction_category(self.conn, transaction_id, category_id, merchant_text=description)
        self.refresh()
