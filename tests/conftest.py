"""pytest 共通フィクスチャ。

app.py はモジュールトップで init_db() と print(DB_PATH) を実行するため、
import の前に環境変数（SECRET_KEY / SHIFT_DB_PATH / ADMIN_INIT_PASSWORD）を
セットしておく必要がある。
"""

import importlib
import os
import secrets
import sys
import tempfile

import pytest


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """毎テストで app.py をクリーン import し、一時 DB を使う。"""
    db_path = tmp_path / "shift.db"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(db_path))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "adminpass1")
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

    def _login(username="admin", password="adminpass1"):
        resp = client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )
        return resp

    return _login


@pytest.fixture
def admin_client(client, login):
    """初期 admin としてログイン済み + 初回パスワード変更も済ませた状態。"""
    # 1) admin/adminpass1 でログイン → must_change_password=1 なので /change_password に強制誘導
    login("admin", "adminpass1")
    # 2) 新パスワードに変更
    resp = client.post(
        "/change_password",
        data={"password_current": "adminpass1", "password_new": "adminpass2"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    # 3) 新パスワードで再ログイン
    login("admin", "adminpass2")
    return client
