"""環境変数による fail-fast のテスト（B, S, C#11）。"""

import importlib
import secrets
import sys

import pytest


def _reload_app(monkeypatch, env):
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_prod_without_secret_key_fails(monkeypatch, tmp_path):
    """B: APP_ENV=production で SECRET_KEY 未設定なら起動失敗。"""
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _reload_app(
            monkeypatch,
            {
                "APP_ENV": "production",
                "SECRET_KEY": None,
                "SHIFT_DB_PATH": str(tmp_path / "shift.db"),
                "TRUSTED_PROXY_HOPS": "0",
            },
        )
    sys.modules.pop("app", None)


def test_prod_with_relative_db_path_fails(monkeypatch):
    """S: 本番では SHIFT_DB_PATH が絶対パスでないと起動失敗。"""
    with pytest.raises(RuntimeError, match="SHIFT_DB_PATH"):
        _reload_app(
            monkeypatch,
            {
                "APP_ENV": "production",
                "SECRET_KEY": secrets.token_hex(16),
                "SHIFT_DB_PATH": "relative/shift.db",
                "TRUSTED_PROXY_HOPS": "0",
            },
        )
    sys.modules.pop("app", None)


@pytest.mark.parametrize("db_path", [None, "   "])
def test_prod_requires_explicit_nonempty_db_path(monkeypatch, db_path):
    with pytest.raises(RuntimeError, match="SHIFT_DB_PATH"):
        _reload_app(
            monkeypatch,
            {
                "APP_ENV": "production",
                "SECRET_KEY": secrets.token_hex(16),
                "SHIFT_DB_PATH": db_path,
                "TRUSTED_PROXY_HOPS": "0",
            },
        )
    sys.modules.pop("app", None)


def test_empty_rate_limit_storage_uri_fails(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="RATELIMIT_STORAGE_URI"):
        _reload_app(
            monkeypatch,
            {
                "APP_ENV": "development",
                "SECRET_KEY": secrets.token_hex(16),
                "SHIFT_DB_PATH": str(tmp_path / "shift.db"),
                "RATELIMIT_STORAGE_URI": " ",
                "TRUSTED_PROXY_HOPS": "0",
            },
        )
    sys.modules.pop("app", None)


def test_invalid_trusted_proxy_hops_fails(monkeypatch, tmp_path):
    """C#11: 不正値（非数値・負数）の TRUSTED_PROXY_HOPS は RuntimeError。"""
    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_HOPS"):
        _reload_app(
            monkeypatch,
            {
                "APP_ENV": "development",
                "SECRET_KEY": secrets.token_hex(16),
                "SHIFT_DB_PATH": str(tmp_path / "shift.db"),
                "TRUSTED_PROXY_HOPS": "abc",
            },
        )
    sys.modules.pop("app", None)

    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_HOPS"):
        _reload_app(
            monkeypatch,
            {
                "APP_ENV": "development",
                "SECRET_KEY": secrets.token_hex(16),
                "SHIFT_DB_PATH": str(tmp_path / "shift.db"),
                "TRUSTED_PROXY_HOPS": "-1",
            },
        )
    sys.modules.pop("app", None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("BACKUP_ON_STARTUP", "sometimes"),
        ("TRUST_CF_CONNECTING_IP", "trusted"),
        ("AUDIT_RETENTION", "-1"),
        ("SESSION_ABSOLUTE_HOURS", "0"),
    ],
)
def test_invalid_operational_settings_fail(monkeypatch, tmp_path, name, value):
    with pytest.raises(RuntimeError, match=name):
        _reload_app(
            monkeypatch,
            {
                "APP_ENV": "development",
                "SECRET_KEY": secrets.token_hex(16),
                "SHIFT_DB_PATH": str(tmp_path / "shift.db"),
                "TRUSTED_PROXY_HOPS": "0",
                name: value,
            },
        )
    sys.modules.pop("app", None)


def test_import_does_not_create_database(monkeypatch, tmp_path):
    db_path = tmp_path / "shift.db"
    mod = _reload_app(
        monkeypatch,
        {
            "APP_ENV": "development",
            "SECRET_KEY": secrets.token_hex(16),
            "SHIFT_DB_PATH": str(db_path),
            "ADMIN_INIT_PASSWORD": "Admin-Initial-Passphrase-2026",
            "TRUSTED_PROXY_HOPS": "0",
        },
    )
    try:
        assert not db_path.exists()
        mod.init_db()
        assert db_path.exists()
    finally:
        sys.modules.pop("app", None)


def test_prod_without_initial_admin_password_is_not_ready(monkeypatch, tmp_path):
    mod = _reload_app(
        monkeypatch,
        {
            "APP_ENV": "production",
            "SECRET_KEY": secrets.token_hex(32),
            "SHIFT_DB_PATH": str(tmp_path / "shift.db"),
            "ADMIN_INIT_PASSWORD": None,
            "TRUSTED_PROXY_HOPS": "0",
            "BACKUP_ON_STARTUP": "0",
        },
    )
    try:
        with mod.app.test_client() as client:
            assert client.get("/healthz").status_code == 200
            assert client.get("/readyz").status_code == 503
    finally:
        sys.modules.pop("app", None)
