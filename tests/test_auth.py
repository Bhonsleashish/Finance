from __future__ import annotations

import pytest

from finance_os import auth


@pytest.fixture(autouse=True)
def isolated_secrets(tmp_path, monkeypatch):
    """Point the auth module at a throwaway secrets file per test, and clean
    up so tests never touch the developer's real config/secrets.yaml."""
    fake_secrets = tmp_path / "secrets.yaml"
    monkeypatch.setattr(auth, "SECRETS_PATH", fake_secrets)
    yield
    if fake_secrets.exists():
        fake_secrets.unlink()


def test_no_password_by_default():
    assert auth.is_password_set() is False
    assert auth.verify_password("anything") is False


def test_set_and_verify_password():
    auth.set_password("correct-horse-battery")
    assert auth.is_password_set() is True
    assert auth.verify_password("correct-horse-battery") is True
    assert auth.verify_password("wrong-password") is False


def test_password_too_short_rejected():
    with pytest.raises(ValueError):
        auth.set_password("abc")
    assert auth.is_password_set() is False


def test_clear_password():
    auth.set_password("correct-horse-battery")
    assert auth.clear_password() is True
    assert auth.is_password_set() is False
    assert auth.clear_password() is False  # already cleared


def test_password_is_hashed_not_stored_in_plaintext():
    auth.set_password("correct-horse-battery")
    raw_contents = auth.SECRETS_PATH.read_text()
    assert "correct-horse-battery" not in raw_contents
