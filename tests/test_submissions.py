"""V28: 提出状況の一覧（管理者専用）のテスト。"""


def _add_worker(admin_client, username="taro", name="太郎"):
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create", "username": username,
            "password": "Taro-Initial-Passphrase-2026", "name": name, "role": "worker", "color": "#e8f5e9",
        },
    )


def test_submissions_shows_unsubmitted_worker(admin_client):
    _add_worker(admin_client)
    resp = admin_client.get("/submissions?year=2026&month=6")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "太郎" in body
    assert "未提出" in body


def test_submissions_reflects_submission(admin_client):
    # admin 自身が 2026-06 の希望を提出
    admin_client.post("/", data={"year": "2026", "month": "6", "day_1": "〇"})
    resp = admin_client.get("/submissions?year=2026&month=6")
    body = resp.get_data(as_text=True)
    assert "提出済" in body
    assert "<td>1</td>" in body
    assert "2026-" in body


def test_submissions_forbidden_for_worker(admin_client):
    _add_worker(admin_client)
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": "taro", "password": "Taro-Initial-Passphrase-2026"})
    admin_client.post(
        "/change_password",
        data={"password_current": "Taro-Initial-Passphrase-2026", "password_new": "Taro-Changed-Passphrase-2026"},
    )
    admin_client.post("/login", data={"username": "taro", "password": "Taro-Changed-Passphrase-2026"})
    assert admin_client.get("/submissions").status_code == 403


def test_submissions_anonymous_redirects(app_module):
    with app_module.app.test_client() as c:
        resp = c.get("/submissions", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_submissions_invalid_month_no_500(admin_client):
    assert admin_client.get("/submissions?month=13").status_code == 200
