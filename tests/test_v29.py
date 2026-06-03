"""V29: 実運用(10名)移行のための堅牢化テスト。

- client_ip(): TRUST_CF_CONNECTING_IP に応じて CF-Connecting-IP を優先/無視
- 管理者ルートの認可統一（職員→403）＋ authz_fail 監査
- MAX_CONTENT_LENGTH 超過 → 413
- backup_db(): バックアップ生成＋世代保持＋健全性
- users.name の UNIQUE 索引
"""

import glob
import importlib
import os
import secrets
import sqlite3
import sys
from contextlib import closing


def _become_worker(admin_client, username="taro", name="太郎"):
    """admin_client 上で職員を作成し、その職員でログイン済みにする。"""
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create", "username": username,
            "password": "taropass1", "name": name, "role": "worker", "color": "#e8f5e9",
        },
    )
    admin_client.get("/logout")
    admin_client.post("/login", data={"username": username, "password": "taropass1"})
    admin_client.post(
        "/change_password",
        data={"password_current": "taropass1", "password_new": "taropass2"},
    )
    admin_client.post("/login", data={"username": username, "password": "taropass2"})


# ===== client_ip / CF-Connecting-IP =====


def test_client_ip_prefers_cf_when_trusted(monkeypatch, tmp_path):
    """TRUST_CF_CONNECTING_IP=1 のとき CF-Connecting-IP の先頭値を採用。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(tmp_path / "shift.db"))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "adminpass1")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    monkeypatch.setenv("TRUST_CF_CONNECTING_IP", "1")
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    try:
        with mod.app.test_request_context(
            "/", headers={"CF-Connecting-IP": "203.0.113.9, 10.0.0.1"}
        ):
            assert mod.client_ip() == "203.0.113.9"
    finally:
        sys.modules.pop("app", None)


def test_client_ip_rejects_malformed_cf_header(monkeypatch, tmp_path):
    """V29: 信頼設定中でも不正な CF-Connecting-IP は採用せず remote_addr へフォールバック。
    妥当な IPv6 は採用する（ipaddress 検証）。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(tmp_path / "shift.db"))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "adminpass1")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    monkeypatch.setenv("TRUST_CF_CONNECTING_IP", "1")
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    try:
        with mod.app.test_request_context(
            "/",
            headers={"CF-Connecting-IP": "not-an-ip<script>"},
            environ_overrides={"REMOTE_ADDR": "198.51.100.5"},
        ):
            assert mod.client_ip() == "198.51.100.5"  # 不正値→フォールバック
        with mod.app.test_request_context(
            "/", headers={"CF-Connecting-IP": "2001:db8::1"}
        ):
            assert mod.client_ip() == "2001:db8::1"  # 妥当な IPv6 は採用
    finally:
        sys.modules.pop("app", None)


def test_client_ip_ignores_cf_when_not_trusted(app_module):
    """既定（信頼しない）では CF ヘッダを無視し remote_addr を使う（偽装防止）。"""
    with app_module.app.test_request_context(
        "/",
        headers={"CF-Connecting-IP": "203.0.113.9"},
        environ_overrides={"REMOTE_ADDR": "198.51.100.5"},
    ):
        assert app_module.client_ip() == "198.51.100.5"


# ===== 認可統一 ＋ authz_fail =====


def test_worker_gets_403_on_index_and_manage_users(admin_client, app_module):
    """V29: 職員が `/`・`/manage_users` にアクセスすると 403（旧: login へ redirect）。"""
    _become_worker(admin_client)
    assert admin_client.get("/").status_code == 403
    assert admin_client.get("/manage_users").status_code == 403


def test_authz_fail_is_audited(admin_client, app_module):
    """V29: 職員の管理ルートアクセス（403）は authz_fail として監査ログに残る。"""
    _become_worker(admin_client)
    admin_client.get("/manage_users")
    admin_client.get("/logs")
    with closing(app_module.get_db()) as conn:
        rows = conn.execute(
            "SELECT actor, target FROM audit_log WHERE action='authz_fail'"
        ).fetchall()
    assert len(rows) >= 2
    assert all(r[0] == "taro" for r in rows)  # actor は職員
    assert any("/manage_users" in (r[1] or "") for r in rows)


def test_anonymous_admin_route_redirects_to_login(app_module):
    """未ログインは 403 ではなく login へ。"""
    with app_module.app.test_client() as c:
        resp = c.get("/manage_users", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ===== MAX_CONTENT_LENGTH -> 413 =====


def test_oversized_request_returns_413(admin_client):
    """V29: 本文サイズ上限超過は 413（親切ページ）。"""
    big = "x" * (300 * 1024)
    resp = admin_client.post(
        "/change_password",
        data={"password_current": "a", "password_new": big},
    )
    assert resp.status_code == 413


def test_max_content_length_configured(app_module):
    assert app_module.app.config["MAX_CONTENT_LENGTH"] == 256 * 1024


# ===== backup_db =====


def test_backup_db_creates_and_prunes(app_module, monkeypatch):
    """V29: backup_db() は世代を作り、BACKUP_KEEP を超えた古い世代を削除する。最新は健全。"""
    monkeypatch.setattr(app_module, "BACKUP_KEEP", 3)
    last = None
    for _ in range(6):
        last = app_module.backup_db()
    bdir = os.path.dirname(last)
    files = glob.glob(os.path.join(bdir, "shift-*.db"))
    assert len(files) == 3
    with closing(sqlite3.connect(last)) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        names = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"users", "shifts"} <= names


# ===== users.name UNIQUE index =====


def test_users_name_unique_index_present(app_module):
    with closing(app_module.get_db()) as conn:
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_users_name'"
        ).fetchone()
    assert idx is not None


def test_backup_keep_clamped_to_min_1(monkeypatch, tmp_path):
    """V29: BACKUP_KEEP=0/負数は剪定無効化に倒れず最低 1 に clamp される。"""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(tmp_path / "shift.db"))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "adminpass1")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    monkeypatch.setenv("BACKUP_KEEP", "0")
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    try:
        assert mod.BACKUP_KEEP == 1
    finally:
        sys.modules.pop("app", None)
