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
