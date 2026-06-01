"""V27: セキュリティ強化のテスト（パスワード方針・CSP/HSTS・ログイン列挙対策）。"""

import importlib
import secrets
import sys


def test_password_policy_length_and_chars(app_module):
    """8文字以上を要求し、記号・空白を許可し、長すぎる入力は拒否する。"""
    f = app_module.is_valid_password
    assert f(None) is False
    assert f("abc") is False           # 短すぎ
    assert f("1234567") is False       # 7文字
    assert f("12345678") is True       # 8文字ちょうど
    assert f("p@ss w0rd") is True      # 記号・空白OK（旧 .isalnum() では弾かれていた）
    assert f("a" * 128) is True        # 上限ちょうど
    assert f("a" * 129) is False       # 上限超過


def test_csp_and_baseline_headers(client):
    """CSP と既存の軽量ヘッダが付与される。"""
    resp = client.get("/login")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "form-action 'self'" in csp
    assert resp.headers.get("X-Frame-Options") == "DENY"


def test_hsts_absent_in_development(client):
    """開発モードでは HSTS を付けない（HTTP 開発を妨げない）。"""
    resp = client.get("/login")
    assert "Strict-Transport-Security" not in resp.headers


def test_hsts_present_in_production(tmp_path, monkeypatch):
    """本番モードでは HSTS が付与され、CSP も付く。"""
    db_path = tmp_path / "shift.db"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "adminpass1")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")

    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    mod.app.config["TESTING"] = True
    mod.limiter.enabled = False
    mod.app.config["WTF_CSRF_ENABLED"] = False
    try:
        with mod.app.test_client() as c:
            resp = c.get("/login")
            hsts = resp.headers.get("Strict-Transport-Security", "")
            assert "max-age=31536000" in hsts
            assert "includeSubDomains" in hsts
            assert "default-src 'self'" in resp.headers.get("Content-Security-Policy", "")
    finally:
        sys.modules.pop("app", None)


def test_login_unknown_user_generic_and_no_session(client):
    """存在しない ID でも、存在ユーザーの誤パスワードと同じ汎用エラー＋セッション無し。"""
    resp = client.post(
        "/login",
        data={"username": "nonexistent_user", "password": "whatever12"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "正しくありません" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert "username" not in s
