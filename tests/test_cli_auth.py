from __future__ import annotations

import pytest
from typer.testing import CliRunner

from finance_os import auth
from finance_os.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_secrets(tmp_path, monkeypatch):
    fake_secrets = tmp_path / "secrets.yaml"
    monkeypatch.setattr(auth, "SECRETS_PATH", fake_secrets)
    yield
    if fake_secrets.exists():
        fake_secrets.unlink()


def test_auth_status_exit_code_reflects_password_state():
    """The Mac launcher script (and any other automation) branches on this
    exit code — `if ! finance auth status; then ...set a password...` — so
    a regression here would silently break that flow."""
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 1

    auth.set_password("correct-horse-battery")
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
