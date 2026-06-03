"""V28: 監査ログ（操作ログ）のテスト。

観点: 主要イベントの記録 / 失敗ログの試行ID / 機密値（パスワード・ハッシュ・備考本文）
の非記録 / /logs の認可 / retention。
"""

from contextlib import closing


def _actions(app_module):
    with closing(app_module.get_db()) as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT action FROM audit_log ORDER BY id"
            ).fetchall()
        ]


def _all_text(app_module):
    with closing(app_module.get_db()) as conn:
        rows = conn.execute(
            "SELECT ts, actor, actor_name, action, target, detail, ip FROM audit_log"
        ).fetchall()
    return " ".join(str(r) for r in rows)


def _add_worker(admin_client, username="taro", name="太郎", pw="taropass1"):
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create", "username": username,
            "password": pw, "name": name, "role": "worker", "color": "#e8f5e9",
        },
    )


def test_login_success_and_logout_logged(client, login, app_module):
    login("admin", "adminpass1")
    client.get("/logout")
    acts = _actions(app_module)
    assert "login_success" in acts
    assert "logout" in acts


def test_login_failure_logged_with_attempted_id(client, login, app_module):
    login("admin", "wrongpass")
    login("ghost", "wrongpass")
    with closing(app_module.get_db()) as conn:
        actors = [
            r[0]
            for r in conn.execute(
                "SELECT actor FROM audit_log WHERE action='login_fail'"
            ).fetchall()
        ]
    assert "admin" in actors  # 存在ユーザーの誤パスワード
    assert "ghost" in actors  # 未知IDも試行として記録


def test_user_and_password_events_logged(admin_client, app_module):
    _add_worker(admin_client)
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "edit", "original_username": "taro",
            "name": "太郎2", "role": "worker", "color": "#fff8e1",
            "password": "newtaro9",
        },
    )
    admin_client.post(
        "/manage_users",
        data={"action": "toggle", "username": "taro", "current_status": "1"},
    )
    acts = _actions(app_module)
    # password_change は admin_client フィクスチャの初回変更で既に発生
    for need in ("password_change", "user_create", "user_edit",
                 "admin_password_set", "user_toggle"):
        assert need in acts, need


def test_request_submit_logged_without_remark_body(admin_client, app_module):
    admin_client.post(
        "/", data={"year": "2026", "month": "6", "day_1": "〇", "remark_1": "SECRET_REMARK_BODY"}
    )
    assert "request_submit" in _actions(app_module)
    # 備考本文は監査ログに出さない
    assert "SECRET_REMARK_BODY" not in _all_text(app_module)


def test_no_passwords_or_hashes_in_audit_log(admin_client, app_module):
    _add_worker(admin_client)
    blob = _all_text(app_module)
    for secret in ("adminpass1", "adminpass2", "taropass1", "scrypt"):
        assert secret not in blob


def test_logs_route_redirects_anonymous(app_module):
    with app_module.app.test_client() as c:
        resp = c.get("/logs", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_logs_route_ok_for_admin(admin_client):
    resp = admin_client.get("/logs")
    assert resp.status_code == 200


def test_logs_route_forbidden_for_worker(admin_client):
    _add_worker(admin_client)
    admin_client.get("/logout")
    admin_client.post("/login", data={"username": "taro", "password": "taropass1"})
    admin_client.post(
        "/change_password",
        data={"password_current": "taropass1", "password_new": "taropass2"},
    )
    admin_client.post("/login", data={"username": "taro", "password": "taropass2"})
    assert admin_client.get("/logs").status_code == 403


def test_audit_retention_caps_rows(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "AUDIT_RETENTION", 5)
    with closing(app_module.get_db()) as conn, conn:
        for i in range(20):
            app_module.log_action(conn, "login_fail", actor=f"u{i}")
    with closing(app_module.get_db()) as conn:
        n = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert n <= 5
