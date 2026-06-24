"""ログイン、パスワード変更、セッション衛生のテスト。"""

from datetime import timedelta

from time_utils import now_utc


def test_login_success_clears_session_and_only_username_stored(client, login, app_module):
    """V11: ログイン成功後、session には username だけが残る（role/name は格納しない）。
    P: 旧セッション値も破棄されている。
    """
    with client.session_transaction() as s:
        s["leftover"] = "old_value"
    resp = login("admin", "Admin-Initial-Passphrase-2026")
    assert resp.status_code == 302
    with client.session_transaction() as s:
        assert s.get("username") == "admin"
        assert "role" not in s
        assert "name" not in s
        assert "leftover" not in s


def test_login_failure_no_session(client, login):
    resp = login("admin", "wrongpass")
    assert resp.status_code == 200
    assert "正しくありません" in resp.get_data(as_text=True)
    with client.session_transaction() as s:
        assert "username" not in s


def test_change_password_requires_login(client):
    """V1: 未ログインで /change_password を叩くとログインへリダイレクト。"""
    resp = client.get("/change_password", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_change_password_post_requires_login(client):
    """V1: 未ログインの POST も login へ。username 当て攻撃面が無いこと。"""
    resp = client.post(
        "/change_password",
        data={"password_current": "x", "password_new": "y1234567"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_no_forced_password_change(client, login):
    """強制変更は廃止。初回 admin でも menu/admin 等にそのまま入れる
    （/change_password へ強制誘導されない）。"""
    login("admin", "Admin-Initial-Passphrase-2026")
    for path in ("/menu", "/", "/admin", "/manage_users"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, path


def test_change_password_and_help_accessible(client, login):
    """パスワード変更・ヘルプは開け、POSTログアウトは login へ。"""
    login("admin", "Admin-Initial-Passphrase-2026")
    for path in ("/change_password", "/help"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, path
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_change_password_updates_and_clears_session(client, login, app_module):
    """変更成功でセッションは破棄されログインへ。新PWでのみ再ログインできる。"""
    login("admin", "Admin-Initial-Passphrase-2026")
    resp = client.post(
        "/change_password",
        data={"password_current": "Admin-Initial-Passphrase-2026", "password_new": "New-Admin-Passphrase-2026"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    # セッションは破棄されている
    with client.session_transaction() as s:
        assert "username" not in s
    # 旧パスワードではログインできない
    resp_old = login("admin", "Admin-Initial-Passphrase-2026")
    assert resp_old.status_code == 200
    # 新パスワードでログイン可能 → must_change_password が解除されている
    resp_new = login("admin", "New-Admin-Passphrase-2026")
    assert resp_new.status_code == 302
    resp_menu = client.get("/menu", follow_redirects=False)
    assert resp_menu.status_code == 200


def test_change_password_rejects_short_password(client, login):
    login("admin", "Admin-Initial-Passphrase-2026")
    resp = client.post(
        "/change_password",
        data={"password_current": "Admin-Initial-Passphrase-2026", "password_new": "abc"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "新しいパスワード" in resp.get_data(as_text=True)


def test_change_password_rejects_wrong_current(client, login):
    login("admin", "Admin-Initial-Passphrase-2026")
    resp = client.post(
        "/change_password",
        data={"password_current": "WRONG", "password_new": "New-Admin-Passphrase-2026"},
        follow_redirects=False,
    )
    assert resp.status_code == 200


def test_logout_clears_session(admin_client):
    admin_client.post("/logout")
    with admin_client.session_transaction() as s:
        assert "username" not in s


def test_get_logout_does_not_change_session(admin_client):
    resp = admin_client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/menu" in resp.headers["Location"]
    with admin_client.session_transaction() as session_data:
        assert session_data["username"] == "admin"


def test_absolute_session_timeout_requires_login(admin_client):
    with admin_client.session_transaction() as session_data:
        session_data["authenticated_at"] = (
            now_utc() - timedelta(hours=25)
        ).isoformat(timespec="seconds")
    resp = admin_client.get("/menu", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_malformed_absolute_session_timestamp_fails_closed(admin_client):
    with admin_client.session_transaction() as session_data:
        session_data["authenticated_at"] = "not-a-timestamp"
    resp = admin_client.get("/menu", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    with admin_client.session_transaction() as session_data:
        assert "username" not in session_data


def test_naive_absolute_session_timestamp_fails_closed(admin_client):
    with admin_client.session_transaction() as session_data:
        session_data["authenticated_at"] = "2026-06-23T10:00:00"
    resp = admin_client.get("/menu", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_audit_failure_does_not_block_login_or_logout(
    client, app_module, monkeypatch
):
    monkeypatch.setattr(
        app_module,
        "log_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("audit unavailable")
        ),
    )
    resp = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "Admin-Initial-Passphrase-2026",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    resp = client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    with client.session_transaction() as session_data:
        assert "username" not in session_data


def test_admin_html_does_not_contain_plaintext_password(admin_client, app_module):
    """A: パスワードが HTML に出ない。"""
    resp = admin_client.get("/manage_users")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Admin-Initial-Passphrase-2026" not in body
    assert "Admin-Changed-Passphrase-2026" not in body
