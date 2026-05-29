"""ログイン / change_password / セッション衛生のテスト（A, P, Q, V1, V8, V11, V23）。"""

from flask import session


def test_login_success_clears_session_and_only_username_stored(client, login, app_module):
    """V11: ログイン成功後、session には username だけが残る（role/name は格納しない）。
    P: 旧セッション値も破棄されている。
    """
    with client.session_transaction() as s:
        s["leftover"] = "old_value"
    resp = login("admin", "adminpass1")
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


def test_must_change_password_forces_redirect(client, login):
    """V23: 初回 admin は must_change_password=1。menu/admin/manage_users 等は強制的に
    /change_password へリダイレクトされる。"""
    login("admin", "adminpass1")
    for path in ("/menu", "/", "/admin", "/manage_users"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302, path
        assert "/change_password" in resp.headers["Location"], path


def test_must_change_password_allows_change_logout_help(client, login):
    """V23: change_password / logout / help / static は強制リダイレクトの対象外。"""
    login("admin", "adminpass1")
    for path in ("/change_password", "/help"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, path
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_change_password_clears_flag_and_session(client, login, app_module):
    """V23: 変更成功で must_change_password=0、セッションは破棄されログインへ。"""
    login("admin", "adminpass1")
    resp = client.post(
        "/change_password",
        data={"password_current": "adminpass1", "password_new": "newpass99"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
    # セッションは破棄されている
    with client.session_transaction() as s:
        assert "username" not in s
    # 旧パスワードではログインできない
    resp_old = login("admin", "adminpass1")
    assert resp_old.status_code == 200
    # 新パスワードでログイン可能 → must_change_password が解除されている
    resp_new = login("admin", "newpass99")
    assert resp_new.status_code == 302
    resp_menu = client.get("/menu", follow_redirects=False)
    assert resp_menu.status_code == 200


def test_change_password_rejects_short_password(client, login):
    login("admin", "adminpass1")
    resp = client.post(
        "/change_password",
        data={"password_current": "adminpass1", "password_new": "abc"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "新しいパスワード" in resp.get_data(as_text=True)


def test_change_password_rejects_wrong_current(client, login):
    login("admin", "adminpass1")
    resp = client.post(
        "/change_password",
        data={"password_current": "WRONG", "password_new": "newpass99"},
        follow_redirects=False,
    )
    assert resp.status_code == 200


def test_worker_redirects_to_menu_when_accessing_other(admin_client):
    """V8: 他人の /worker/<name> を叩いたらログインではなくメニューへ。"""
    resp = admin_client.get("/worker/別人", follow_redirects=False)
    assert resp.status_code == 302
    assert "/menu" in resp.headers["Location"]


def test_logout_clears_session(admin_client):
    admin_client.get("/logout")
    with admin_client.session_transaction() as s:
        assert "username" not in s


def test_admin_html_does_not_contain_plaintext_password(admin_client, app_module):
    """A: パスワードが HTML に出ない。"""
    resp = admin_client.get("/manage_users")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "adminpass1" not in body
    assert "adminpass2" not in body
