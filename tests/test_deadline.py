"""締め切り（deadline）とスタッフロック・管理者代理編集のテスト。

仕様:
- 締め切り未設定: スタッフは編集可。
- 締め切り日当日0:00(JST)以降: スタッフは読み取り専用・保存しても DB 不変。
- スタッフの保存先は前月・当月・翌月のみ（画面が提供する月＋月替わり猶予）。
- 管理者は締め切り後も /staff/<username> と / で保存できる（月の制限なし）。

日付は実行時の JST 現在月（Y/M）を基準にし、ハードコード年月による時限故障を防ぐ。
"""

from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
WPW = "Taro-Passphrase-2026"

# テスト対象月 = 実行時点の JST 当月（worker の既定保存先と一致）
_NOW = datetime.now(JST)
Y, M = _NOW.year, _NOW.month


def _add_worker(admin_client, username="taro", name="太郎"):
    admin_client.post(
        "/manage_users",
        data={"action": "add", "mode": "create", "username": username,
              "password": WPW, "name": name, "role": "worker", "color": "#e8f5e9"},
    )


def _login_worker(admin_client, username="taro"):
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": username, "password": WPW})


def _set_deadline(admin_client, year, month, date_str):
    return admin_client.post(
        "/deadline",
        data={"year": str(year), "month": str(month), "deadline": date_str},
        follow_redirects=False,
    )


def _count(app_module, username, year=Y, month=M):
    with closing(app_module.get_db()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM shifts WHERE username=? AND year=? AND month=?",
            (username, year, month),
        ).fetchone()[0]


def _submit(admin_client, route="/worker", year=Y, month=M, **extra):
    data = {"year": str(year), "month": str(month), "day_1": "〇"}
    data.update(extra)
    return admin_client.post(route, data=data, follow_redirects=False)


# ===== スタッフのロック =====

def test_worker_can_submit_without_deadline(admin_client, app_module):
    _add_worker(admin_client)
    _login_worker(admin_client)
    resp = _submit(admin_client)
    assert resp.status_code == 302
    assert "submitted=true" in resp.headers["Location"]
    assert _count(app_module, "taro") > 0


def test_future_deadline_keeps_worker_editable(admin_client, app_module):
    _add_worker(admin_client)
    _set_deadline(admin_client, Y, M, "2999-12-31")
    _login_worker(admin_client)
    assert _submit(admin_client).status_code == 302
    assert _count(app_module, "taro") > 0


def test_past_deadline_makes_worker_readonly(admin_client, app_module):
    _add_worker(admin_client)
    _set_deadline(admin_client, Y, M, "2000-01-01")
    _login_worker(admin_client)
    body = admin_client.get(f"/worker?year={Y}&month={M}").get_data(as_text=True)
    assert "締め切りました" in body
    assert "この内容で保存" not in body  # 保存ボタンが出ない


def test_past_deadline_blocks_worker_post(admin_client, app_module):
    _add_worker(admin_client)
    _set_deadline(admin_client, Y, M, "2000-01-01")
    _login_worker(admin_client)
    before = _count(app_module, "taro")
    resp = _submit(admin_client)
    assert resp.status_code == 302  # 保存せず worker へ戻す
    assert _count(app_module, "taro") == before  # DB 不変


def test_deadline_locks_on_the_day_itself(admin_client, app_module, monkeypatch):
    """締め切り日当日(>=)はロック、前日は編集可。"""
    _add_worker(admin_client)
    # 対象月の15日を締め切りにし、now_jst を当日/前日に固定して境界を確認する
    deadline = datetime(Y, M, 15, tzinfo=JST)
    _set_deadline(admin_client, Y, M, deadline.strftime("%Y-%m-%d"))
    _login_worker(admin_client)

    # 当日 0:30 JST → ロック（保存されない）
    monkeypatch.setattr(app_module, "now_jst",
                        lambda: deadline.replace(hour=0, minute=30))
    before = _count(app_module, "taro")
    _submit(admin_client)
    assert _count(app_module, "taro") == before

    # 前日 23:30 JST → 編集可
    monkeypatch.setattr(app_module, "now_jst",
                        lambda: (deadline - timedelta(days=1)).replace(hour=23, minute=30))
    _submit(admin_client)
    assert _count(app_module, "taro") > 0


# ===== スタッフの保存先は前月・当月・翌月のみ =====

def test_worker_post_outside_month_window_rejected(admin_client, app_module):
    """画面が提供しない月への直接 POST は拒否（過去月の書き換え・ごみ登録防止）。"""
    _add_worker(admin_client)
    _login_worker(admin_client)
    far = Y + 2
    resp = _submit(admin_client, year=far, month=M)
    assert resp.status_code == 302
    assert "submitted=true" not in resp.headers["Location"]
    assert _count(app_module, "taro", year=far, month=M) == 0


def test_worker_can_save_previous_month(admin_client, app_module, monkeypatch):
    """月替わり深夜0時をまたいだ送信を弾かないよう、前月は許容する。

    「前月」はサーバの現在月に対する相対値。実行がちょうど月境界をまたぐと
    実クロックの現在月がずれてこのテスト自身が時限故障するため、now_jst を
    当月15日に固定し、保存先ウィンドウを決定論的にする。"""
    _add_worker(admin_client)
    _login_worker(admin_client)
    fixed = datetime(Y, M, 15, 12, 0, tzinfo=JST)
    monkeypatch.setattr(app_module, "now_jst", lambda: fixed)
    prev_last = fixed.replace(day=1) - timedelta(days=1)
    resp = _submit(admin_client, year=prev_last.year, month=prev_last.month)
    assert resp.status_code == 302
    assert "submitted=true" in resp.headers["Location"]
    assert _count(app_module, "taro", year=prev_last.year, month=prev_last.month) > 0


def test_admin_can_edit_any_month(admin_client, app_module):
    """管理者（/staff）は月の制限なし（過去修正の業務ニーズ）。"""
    _add_worker(admin_client)
    far = Y + 2
    resp = _submit(admin_client, route="/staff/taro", year=far, month=M)
    assert resp.status_code == 302
    assert _count(app_module, "taro", year=far, month=M) > 0


# ===== 管理者は締め切り後も編集できる =====

def test_admin_can_edit_staff_after_deadline(admin_client, app_module):
    _add_worker(admin_client)
    _set_deadline(admin_client, Y, M, "2000-01-01")
    resp = _submit(admin_client, route="/staff/taro")
    assert resp.status_code == 302
    assert "/staff/taro" in resp.headers["Location"]
    assert _count(app_module, "taro") > 0


def test_admin_self_input_not_locked(admin_client, app_module):
    _set_deadline(admin_client, Y, M, "2000-01-01")
    resp = _submit(admin_client, route="/")
    assert resp.status_code == 302
    assert _count(app_module, "admin") > 0


def test_staff_edit_logs_proxy_action(admin_client, app_module):
    _add_worker(admin_client)
    _submit(admin_client, route="/staff/taro")
    with closing(app_module.get_db()) as conn:
        acts = [r[0] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "staff_shift_edit" in acts


def test_staff_edit_page_links_back_to_submissions(admin_client):
    """代理編集画面は『提出状況・締め切り』へ戻れる（一覧→編集→一覧の動線）。"""
    _add_worker(admin_client)
    body = admin_client.get(f"/staff/taro?year={Y}&month={M}").get_data(as_text=True)
    assert "提出状況・締め切りに戻る" in body
    assert "/submissions" in body


def test_staff_edit_unknown_user_redirects(admin_client):
    resp = admin_client.get(f"/staff/ghost?year={Y}&month={M}", follow_redirects=False)
    assert resp.status_code == 302
    assert "/submissions" in resp.headers["Location"]


def test_staff_edit_forbidden_for_worker(admin_client):
    _add_worker(admin_client)
    _login_worker(admin_client)
    assert admin_client.get("/staff/taro").status_code == 403


# ===== /deadline ルート =====

def test_deadline_set_and_clear(admin_client, app_module):
    _set_deadline(admin_client, Y, M, "2026-06-25")
    with closing(app_module.get_db()) as conn:
        row = conn.execute(
            "SELECT deadline FROM deadlines WHERE year=? AND month=?", (Y, M)
        ).fetchone()
    assert row[0] == "2026-06-25"
    # 空欄で解除
    _set_deadline(admin_client, Y, M, "")
    with closing(app_module.get_db()) as conn:
        row = conn.execute(
            "SELECT deadline FROM deadlines WHERE year=? AND month=?", (Y, M)
        ).fetchone()
    assert row is None


def test_deadline_invalid_date_rejected(admin_client, app_module):
    _set_deadline(admin_client, Y, M, "2026/06/25")  # 不正な形式
    with closing(app_module.get_db()) as conn:
        row = conn.execute(
            "SELECT deadline FROM deadlines WHERE year=? AND month=?", (Y, M)
        ).fetchone()
    assert row is None  # 保存されていない


def test_deadline_logged(admin_client, app_module):
    _set_deadline(admin_client, Y, M, "2026-06-25")
    with closing(app_module.get_db()) as conn:
        acts = [r[0] for r in conn.execute("SELECT action FROM audit_log").fetchall()]
    assert "deadline_set" in acts


def test_deadline_forbidden_for_worker(admin_client):
    _add_worker(admin_client)
    _login_worker(admin_client)
    resp = admin_client.post(
        "/deadline", data={"year": str(Y), "month": str(M), "deadline": "2026-06-25"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_submissions_shows_deadline_form(admin_client):
    body = admin_client.get(f"/submissions?year={Y}&month={M}").get_data(as_text=True)
    assert 'name="deadline"' in body
    assert "締め切り日" in body


# ===== 旧URLの互換リダイレクト =====

def test_legacy_confirm_redirects(admin_client):
    resp = admin_client.get("/confirm", follow_redirects=False)
    assert resp.status_code == 302
    assert "/submissions" in resp.headers["Location"]


def test_legacy_confirmed_redirects(admin_client):
    resp = admin_client.get("/confirmed", follow_redirects=False)
    assert resp.status_code == 302
    assert "/menu" in resp.headers["Location"]
