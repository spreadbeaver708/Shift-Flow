"""V27: セキュリティ強化のテスト（パスワード方針・CSP/HSTS・ログイン列挙対策）。"""

import importlib
import secrets
import sys


def test_password_policy_length_and_chars(app_module):
    """15文字以上を要求し、記号・空白を許可し、長すぎる入力は拒否する。"""
    f = app_module.is_valid_password
    assert f(None) is False
    assert f("abc") is False           # 短すぎ
    assert f("12345678901234") is False
    assert f("長い パスフレーズ です 2026") is True
    assert f("p@ss phrase 2026") is True
    assert f("a" * 128) is False       # 同じ文字だけ
    assert f("Abc-" * 32) is False     # 短い並びの反復
    assert f("abcdefghabcdefgh") is False
    assert f("上限ちょうど-" + "a" * 121) is True
    assert f("a" * 129) is False       # 上限超過
    assert f("passwordpassword") is False


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
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
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


# ===== V28: セキュリティ基盤の追加検証 =====


def test_csp_script_nonce_and_no_unsafe_inline(client):
    """script/styleともinline実行を許可せず、base-uriも無効にする。"""
    resp = client.get("/login")
    csp = resp.headers.get("Content-Security-Policy", "")
    script_dir = csp.split("script-src", 1)[1].split(";", 1)[0]
    assert "'nonce-" in script_dir
    assert "'unsafe-inline'" not in script_dir
    assert "base-uri 'none'" in csp
    assert "style-src 'self'" in csp
    assert "style-src 'self' 'unsafe-inline'" not in csp


def test_rendered_script_tags_carry_matching_nonce(admin_client):
    """V28: 描画 HTML の全 <script> が CSP ヘッダと同じ nonce を持ち、裸の <script> が無い。"""
    import re

    resp = admin_client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    m = re.search(r"script-src[^;]*'nonce-([^']+)'", csp)
    assert m, "CSP に nonce が無い"
    nonce = m.group(1)
    body = resp.get_data(as_text=True)
    nonces = re.findall(r'<script nonce="([^"]+)"', body)
    assert nonces, "ページに <script nonce> が無い"
    assert all(n == nonce for n in nonces)
    assert "<script>" not in body, "nonce 無しの <script> が残っている"


def test_authenticated_page_has_no_store(admin_client):
    """V28: 認証済みページは Cache-Control: no-store。"""
    resp = admin_client.get("/menu")
    assert resp.headers.get("Cache-Control") == "no-store"


def test_login_page_is_no_store(client):
    """V29: login を含む全動的応答に no-store（CSRF トークン鮮度・CVE-2026-27205 緩和）。
    static は対象外（CSS はキャッシュ可）。"""
    resp = client.get("/login")
    assert resp.headers.get("Cache-Control") == "no-store"
    resp.close()
    static_resp = client.get("/static/style.css")
    assert static_resp.headers.get("Cache-Control") != "no-store"
    static_resp.close()


def test_session_idle_timeout_configured(app_module):
    """V28: アイドルタイムアウト用の設定が入っている。"""
    from datetime import timedelta

    lifetime = app_module.app.config["PERMANENT_SESSION_LIFETIME"]
    assert isinstance(lifetime, timedelta)
    assert lifetime.total_seconds() > 0
    assert app_module.app.config["SESSION_COOKIE_NAME"] == "sfid"


def test_login_marks_session_permanent(client, login):
    """V28: ログイン成功でセッションが permanent（PERMANENT_SESSION_LIFETIME 適用）になる。"""
    login("admin", "Admin-Initial-Passphrase-2026")
    with client.session_transaction() as s:
        assert s.permanent is True
