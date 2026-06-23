"""V28: 確定シフトのテスト。

管理者が職員ごとに確定を保存（confirmed_shifts, username 基準）、職員はチーム全体を
読み取り専用で閲覧（/confirmed）。職員は /confirm 系にアクセスできない（403）。
"""

from contextlib import closing


def _add_worker(admin_client, username="taro", name="太郎"):
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create", "username": username,
            "password": "Taro-Initial-Passphrase-2026", "name": name, "role": "worker", "color": "#e8f5e9",
        },
    )


def _become_worker(admin_client, username="taro"):
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": username, "password": "Taro-Initial-Passphrase-2026"})
    admin_client.post(
        "/change_password",
        data={"password_current": "Taro-Initial-Passphrase-2026", "password_new": "Taro-Changed-Passphrase-2026"},
    )
    admin_client.post("/login", data={"username": username, "password": "Taro-Changed-Passphrase-2026"})


def test_admin_saves_confirmed_shift(admin_client, app_module):
    _add_worker(admin_client)
    resp = admin_client.post(
        "/confirm/taro", data={"year": "2026", "month": "6", "day_1": "〇"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    with closing(app_module.get_db()) as conn:
        rows = conn.execute(
            "SELECT username, day, status FROM confirmed_shifts "
            "WHERE year=2026 AND month=6"
        ).fetchall()
    assert any(r[0] == "taro" and r[1] == 1 and r[2] == "〇" for r in rows)


def test_confirm_save_is_logged(admin_client, app_module):
    _add_worker(admin_client)
    admin_client.post("/confirm/taro", data={"year": "2026", "month": "6", "day_1": "〇"})
    with closing(app_module.get_db()) as conn:
        acts = [r[0] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "confirm_save" in acts


def test_confirm_save_logs_target_username(admin_client, app_module):
    """V28: confirm_save の監査ログ detail に対象職員の安定ID(username)が残る
    （表示名変更後も「誰の確定を編集したか」を追跡できる）。"""
    _add_worker(admin_client)  # taro / 太郎
    admin_client.post("/confirm/taro", data={"year": "2026", "month": "6", "day_1": "〇"})
    with closing(app_module.get_db()) as conn:
        row = conn.execute(
            "SELECT detail FROM audit_log WHERE action='confirm_save' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert "taro" in row[0]


def test_confirm_editor_shows_request_hint(admin_client):
    _add_worker(admin_client)
    resp = admin_client.get("/confirm/taro?year=2026&month=6")
    assert resp.status_code == 200
    assert "本人の希望：" in resp.get_data(as_text=True)


def test_confirm_user_unknown_redirects(admin_client):
    resp = admin_client.post(
        "/confirm/nonexistent", data={"year": "2026", "month": "6", "day_1": "〇"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/confirm" in resp.headers["Location"]


def test_confirm_routes_forbidden_for_worker(admin_client):
    _add_worker(admin_client)
    _become_worker(admin_client)
    assert admin_client.get("/confirm").status_code == 403
    assert admin_client.get("/confirm/taro").status_code == 403


def test_confirmed_view_is_readonly_and_visible_to_worker(admin_client):
    _add_worker(admin_client)
    admin_client.post("/confirm/taro", data={"year": "2026", "month": "6", "day_1": "〇"})
    _become_worker(admin_client)
    resp = admin_client.get("/confirmed?year=2026&month=6")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "太郎" in body          # チーム全体が見える
    assert "<form" not in body     # 読み取り専用（編集フォーム無し）


def test_confirmed_anonymous_redirects(app_module):
    with app_module.app.test_client() as c:
        resp = c.get("/confirmed", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_confirmed_invalid_month_no_500(admin_client):
    assert admin_client.get("/confirmed?month=13").status_code == 200
