"""セキュリティヘッダ・CSRF・認可関連のテスト（V2, V9, N, Q）。"""

import importlib
import secrets
import sys


def test_security_headers_present(client):
    """V9: 軽量セキュリティヘッダが付与される。"""
    resp = client.get("/login")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "same-origin"


def test_csrf_error_handler_redirects_to_login(tmp_path, monkeypatch):
    """V2: CSRF トークン無しの POST は 400 ではなく login にリダイレクトされ flash が出る。
    conftest の app_module は WTF_CSRF_ENABLED=False を入れているので、
    このテスト専用にクリーン import で CSRF を有効にする。
    """
    db_path = tmp_path / "shift.db"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")

    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    mod.app.config["TESTING"] = True
    mod.limiter.enabled = False
    mod.app.config["WTF_CSRF_ENABLED"] = True  # ← V2 検証のため有効
    try:
        with mod.app.test_client() as c:
            # トークン無しで login POST → CSRFError → login へ redirect + flash
            resp = c.post(
                "/login",
                data={"username": "admin", "password": "Admin-Initial-Passphrase-2026"},
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "/login" in resp.headers["Location"]
            # 次の GET で flash が表示される
            resp_login = c.get("/login")
            assert "セッションが切れました" in resp_login.get_data(as_text=True)
    finally:
        sys.modules.pop("app", None)


def test_anonymous_admin_page_redirects_to_login(client):
    """フェーズ1 N: 未ログインで /admin はログイン画面へ。"""
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_worker_can_not_access_admin(admin_client, app_module):
    """N: 職員は /admin にアクセスできない（403）。"""
    # 職員 taro を作って、その taro でログインし直す
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    # taro でログイン → 任意でパスワード変更 → 再ログイン（強制変更は廃止済み）
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": "taro", "password": "Taro-Initial-Passphrase-2026"})
    admin_client.post(
        "/change_password",
        data={"password_current": "Taro-Initial-Passphrase-2026", "password_new": "Taro-Changed-Passphrase-2026"},
    )
    admin_client.post("/login", data={"username": "taro", "password": "Taro-Changed-Passphrase-2026"})

    resp = admin_client.get("/admin", follow_redirects=False)
    assert resp.status_code == 403


def test_deactivated_user_session_invalidated(admin_client, app_module):
    """Q: 停止された職員の旧セッションでは /menu に到達できない（DB から再取得）。"""
    # 職員 taro を作って、初期パスワード変更 → ログイン
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    # taro でログイン → 任意でパスワード変更 → 再ログイン（強制変更は廃止済み）
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": "taro", "password": "Taro-Initial-Passphrase-2026"})
    admin_client.post(
        "/change_password",
        data={"password_current": "Taro-Initial-Passphrase-2026", "password_new": "Taro-Changed-Passphrase-2026"},
    )
    admin_client.post("/login", data={"username": "taro", "password": "Taro-Changed-Passphrase-2026"})
    resp = admin_client.get("/menu")
    assert resp.status_code == 200

    # admin で taro を停止
    admin2 = admin_client.application.test_client()
    admin2.post("/login", data={"username": "admin", "password": "Admin-Changed-Passphrase-2026"})
    admin2.post(
        "/manage_users",
        data={"action": "toggle", "username": "taro", "current_status": "1"},
    )

    # taro の旧セッションで /menu → ログインへリダイレクト
    resp = admin_client.get("/menu", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_safe_ym_rejects_out_of_range(admin_client):
    """O: month=13 等の不正値で 500 にならず正常レスポンス。"""
    resp = admin_client.get("/admin?month=13")
    assert resp.status_code == 200
    resp = admin_client.get("/admin?year=9999&month=2")
    assert resp.status_code == 200
