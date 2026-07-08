"""Local password protection for the dashboard.

No cloud auth provider, no external calls — a salted PBKDF2 hash lives in
config/secrets.yaml (already gitignored, never committed). Both the CLI
(`finance auth ...`) and the Streamlit dashboard use this module so there is
exactly one source of truth for "is a password set" and "is this the right
one."
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

import yaml

from finance_os.config import CONFIG_DIR

SECRETS_PATH = CONFIG_DIR / "secrets.yaml"
PBKDF2_ITERATIONS = 200_000


@dataclass
class Credentials:
    salt_hex: str
    hash_hex: str
    iterations: int


def _load_raw() -> dict:
    if not SECRETS_PATH.exists():
        return {}
    with SECRETS_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _save_raw(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with SECRETS_PATH.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh)
    # Best-effort: keep the secrets file readable only by the owner.
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except OSError:
        pass


def get_credentials() -> Credentials | None:
    data = _load_raw().get("dashboard_auth")
    if not data:
        return None
    return Credentials(salt_hex=data["salt"], hash_hex=data["hash"], iterations=data.get("iterations", PBKDF2_ITERATIONS))


def is_password_set() -> bool:
    return get_credentials() is not None


def _hash_password(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def set_password(password: str) -> None:
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    salt = secrets.token_bytes(16)
    digest = _hash_password(password, salt)
    raw = _load_raw()
    raw["dashboard_auth"] = {
        "salt": salt.hex(),
        "hash": digest.hex(),
        "iterations": PBKDF2_ITERATIONS,
    }
    _save_raw(raw)


def clear_password() -> bool:
    raw = _load_raw()
    if "dashboard_auth" not in raw:
        return False
    del raw["dashboard_auth"]
    _save_raw(raw)
    return True


def verify_password(password: str) -> bool:
    creds = get_credentials()
    if creds is None:
        return False
    candidate = _hash_password(password, bytes.fromhex(creds.salt_hex), creds.iterations)
    return hmac.compare_digest(candidate, bytes.fromhex(creds.hash_hex))
