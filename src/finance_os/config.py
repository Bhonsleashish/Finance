"""Central configuration loader.

Reads config/config.yaml (plus optional config/local.yaml overrides) and
exposes strongly-typed, path-resolved settings used by every other module.
Nothing here ever performs network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# Repo root = two levels up from src/finance_os/config.py -> src/finance_os -> src -> root
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass
class Settings:
    raw: dict[str, Any] = field(default_factory=dict)
    project_root: Path = PROJECT_ROOT

    # -- convenience accessors -------------------------------------------------
    @property
    def currency(self) -> str:
        return self.raw.get("app", {}).get("currency", "EUR")

    @property
    def history_start_month(self) -> str:
        return self.raw.get("history", {}).get("start_month", "2026-01")

    @property
    def database_file(self) -> Path:
        rel = self.raw.get("paths", {}).get("database_file", "database/finance.db")
        return self.project_root / rel

    @property
    def data_dir(self) -> Path:
        rel = self.raw.get("paths", {}).get("data_dir", "data")
        return self.project_root / rel

    @property
    def reports_dir(self) -> Path:
        rel = self.raw.get("paths", {}).get("reports_dir", "reports")
        return self.project_root / rel

    @property
    def exports_dir(self) -> Path:
        rel = self.raw.get("paths", {}).get("exports_dir", "data/exports")
        return self.project_root / rel

    @property
    def config_dir(self) -> Path:
        return CONFIG_DIR

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    base = _load_yaml(CONFIG_DIR / "config.yaml")
    local = _load_yaml(CONFIG_DIR / "local.yaml")
    merged = _deep_merge(base, local)
    return Settings(raw=merged)


@lru_cache(maxsize=1)
def load_categories() -> dict:
    return _load_yaml(CONFIG_DIR / "categories.yaml").get("categories", {})


@lru_cache(maxsize=1)
def load_merchants() -> dict:
    return _load_yaml(CONFIG_DIR / "merchants.yaml").get("merchants", {})
