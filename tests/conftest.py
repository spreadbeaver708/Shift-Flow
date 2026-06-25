"""pytest 共通フィクスチャ。

app.py はモジュールトップで init_db() と print(DB_PATH) を実行するため、
import の前に環境変数（SECRET_KEY / SHIFT_DB_PATH / ADMIN_INIT_PASSWORD）を
セットしておく必要がある。
"""

import importlib
import secrets
import sys

import pytest


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """毎テストで app.py をクリーン import し、一時 DB を使う。"""
    db_path = tmp_path / "shift.db"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")

    # app は import 時に init_db() を走らせる。クリーン import のため一度 unload。
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    mod.app.config["TESTING"] = True
    # テスト中はレート制限を無効化（429 が混ざるとシナリオが読みにくい）
    mod.limiter.enabled = False
    # CSRF は既定 OFF（POST 毎にトークン抽出する手間を省く）。
    # V2 の CSRF ハンドラを検証する専用テストでだけ有効化する。
    mod.app.config["WTF_CSRF_ENABLED"] = False
    yield mod
    sys.modules.pop("app", None)


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def login(client):
    """テストヘルパー: 指定 user で /login POST し、セッション cookie を持った client を返す。"""

    def _login(username="admin", password="Admin-Initial-Passphrase-2026"):
        resp = client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )
        return resp

    return _login


@pytest.fixture
def admin_client(client, login):
    """初期 admin としてログイン → 任意でパスワードを変更した状態を作る。

    初回強制変更は撤廃済み（must_change_password 列は互換のため残るが常時 0）。
    後続テストの前提として、初期PWでログイン→/change_password で新PWへ変更→
    新PWで再ログイン、という通常フローを通すだけ（強制誘導は無い）。
    """
    # 1) 初期PWでログイン（強制変更は無く、そのままメニューへ）
    login("admin", "Admin-Initial-Passphrase-2026")
    # 2) 任意のパスワード変更を実施
    resp = client.post(
        "/change_password",
        data={"password_current": "Admin-Initial-Passphrase-2026", "password_new": "Admin-Changed-Passphrase-2026"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # 3) 新パスワードで再ログイン
    login("admin", "Admin-Changed-Passphrase-2026")
    return client
