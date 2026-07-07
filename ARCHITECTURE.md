# Architecture

## Principles

1. **Local-first, always.** One SQLite file (`database/finance.db`) is the
   entire system's state. No network calls exist anywhere in `src/finance_os`
   — not for OCR (Tesseract runs locally), not for the dashboard (Streamlit
   binds to localhost and its own telemetry ping is disabled), not for
   anything else.
2. **Transparent math.** Every number the system produces (a budget line, a
   forecast, a "Buy now" recommendation) can be traced back to a formula in
   the code, not a black-box model. See `analysis/` docstrings.
3. **Config over code.** Categories, merchants and thresholds live in
   `config/*.yaml`, not hardcoded, so extending recognition doesn't require
   touching Python.

## Data flow

```
 PDF / CSV / image
        │
        ▼
 ingest/pdf_extractor.py  ──(scanned page)──▶  ingest/ocr.py  (Tesseract, local)
        │  (native text or OCR text)
        ▼
 ingest/{payslip,bank_statement,csv,receipt}_parser.py   (regex/heuristic parsing)
        │
        ▼
 categorize/categorizer.py   (merchant patterns → fuzzy match → keywords → fallback)
        │
        ▼
 db/repository.py   ──▶   database/finance.db (SQLite)
        │
        ▼
 analysis/*.py   (salary, cashflow, budgeting, goals, forecasting, health, advisor, alerts)
        │
        ▼
 reports/*.py  (weekly/monthly review JSON + CSV/Excel/PDF exporters)
        │
        ▼
 cli/main.py  (Typer)          dashboard/app.py + pages/*.py  (Streamlit)
```

## Package layout (`src/finance_os/`)

- `config.py` — loads `config/*.yaml`, resolves paths relative to the repo
  root. `Settings.database_file`, `.data_dir`, `.reports_dir` etc.
- `db/`
  - `schema.sql` — the entire schema (documents, salary_slips, transactions,
    categories, merchants, budgets, goals, subscriptions, net_worth_snapshots,
    alerts, reviews). Every table is commented.
  - `connection.py` — opens the SQLite file, runs the schema, seeds
    categories/merchants from `config/*.yaml` (idempotent).
  - `repository.py` — every SQL statement in the app lives here. Nothing else
    writes raw SQL.
- `ingest/`
  - `pdf_extractor.py` — PyMuPDF text extraction, falling back to OCR per
    page when the native text layer is too thin (scanned documents).
  - `ocr.py` — thin wrapper around `pytesseract`; degrades gracefully (empty
    string) if Tesseract isn't installed, rather than crashing ingestion.
  - `payslip_parser.py` — line-by-line regex matching against a table of
    German payslip labels (see module docstring for why this is table-driven
    rather than layout-specific).
  - `bank_statement_parser.py` — generic date-prefixed-line heuristic for
    German bank statement PDFs.
  - `csv_importer.py` — auto-detects date/description/amount columns from
    common German/English bank CSV headers.
  - `receipt_parser.py` — merchant/date/total extraction for receipts,
    invoices and screenshots.
  - `ingest_pipeline.py` — orchestrates the above: hashes the file for dedup,
    picks a parser by doc type, categorizes any transactions, writes to the
    DB. This is what `finance ingest` calls.
- `categorize/categorizer.py` — merchant pattern match → fuzzy match
  (rapidfuzz) → category keyword match → fallback to "Miscellaneous". Manual
  corrections (`categorizer.learn_correction`) create a new learned merchant
  pattern, closing the learning loop without any ML model.
- `analysis/` — one module per concern (`salary`, `cashflow`, `networth`,
  `subscriptions`, `budgeting`, `goals`, `forecasting`, `health_score`,
  `advisor`, `alerts`). Each function takes a `sqlite3.Connection` and
  returns plain dataclasses/DataFrames — no hidden state.
- `reports/` — `weekly_review.py` and `monthly_review.py` assemble a single
  JSON-serializable payload from the analysis modules (also cached in the
  `reviews` table); `exporters.py` turns that payload (or the raw ledger)
  into CSV/Excel/PDF.
- `cli/main.py` — Typer app wiring all of the above into `finance <command>`.
- `dashboard/` — Streamlit multipage app: `app.py` is the Overview page,
  `pages/*.py` are Salary / Expenses / Budget / Goals / Subscriptions /
  Forecast / Advisor. `_shared.py` holds the cached DB connection and
  formatting helpers used by every page.

## Why an adaptive budget, not a static one

`analysis/budgeting.py` recomputes the plan every time it's asked:

1. Income = trailing 3-month average net salary (falls back to average
   transaction-ledger income if no payslips have been parsed yet), so one
   bonus month doesn't distort next month's budget.
2. Fixed bills (Housing, Utilities, Insurance, Debt, Subscriptions — see
   `config.yaml: budgeting.fixed_categories`) get their own trailing average;
   the engine doesn't try to shrink your rent.
3. The remaining needs/wants target (from `budgeting.target_allocation`,
   default 50/30/20) is distributed across flexible categories proportional
   to their recent actual spending, capped at 15% growth over their own
   recent average — the budget tightens or loosens with your real behavior,
   not a copy-pasted percentage.
4. Savings is floored by the sum of active goals' committed monthly
   contributions, so a debt-payoff or emergency-fund goal is never
   quietly under-budgeted.

## Why the categorizer learns without an ML model

Real recurring accuracy comes from merchant identity, not sentence
classification. `category_corrections` logs every manual fix; the merchant
token extracted from the corrected description becomes a new row in
`merchants` + `merchant_patterns`, so the *next* transaction from that
merchant matches on step 1 (exact pattern) instead of falling through to
keyword matching or the "Miscellaneous" fallback. This is auditable (you can
read every learned pattern in the `merchants` table) and needs no training
data or GPU.

## Testing

`tests/` uses a `db_conn` fixture (see `conftest.py`) that spins up a fresh
temp SQLite file per test, running the real schema and seed data — no mocks
for the database layer, since SQLite-on-disk is fast enough and this is
exactly the code path production runs. Parsers are tested against realistic
synthetic German payslip/statement/CSV text (see `tests/test_payslip_parser.py`
for what a well-formed test payslip looks like when adding a new label).
