"""シフト入力フローのテスト。"""

from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo


def test_admin_post_redirects_to_index_with_submitted(admin_client):
    """V4: 管理者の POST 後は /worker ではなく / にリダイレクト。"""
    resp = admin_client.post("/", data={"day_1": "〇", "remark_1": ""})
    assert resp.status_code == 302
    loc = resp.headers["Location"]
    assert "/worker" not in loc
    assert "submitted=true" in loc


def test_index_month_links_point_to_index(admin_client):
    """V4: 管理者の月切替リンクは / を指す。"""
    resp = admin_client.get("/?year=2026&month=5")
    body = resp.get_data(as_text=True)
    # 翌月リンクが index ルートを向いていることを確認
    # （url_for('index', ...) は通常 `/?year=...&month=...` を生成）
    assert "/worker/管理者" not in body


def test_shift_input_persists(admin_client, app_module):
    admin_client.post(
        "/",
        data={"year": "2026", "month": "6", "day_1": "〇", "remark_1": "メモ"},
        follow_redirects=False,
    )
    with closing(app_module.get_db()) as conn:
        rows = conn.execute(
            "SELECT day, status FROM shifts WHERE name='管理者'"
        ).fetchall()
    # 日・月・木の該当日には INSERT されている
    assert len(rows) > 0


def test_admin_route_handles_invalid_month_param(admin_client):
    """O: month=13 でも 500 にならない（safe_ym で default に丸め）。"""
    resp = admin_client.get("/?month=13")
    assert resp.status_code == 200


def test_index_html_has_no_inline_onclick(admin_client):
    """V12: index.html の inline onclick が全廃されている（admin 画面）。"""
    resp = admin_client.get("/")
    body = resp.get_data(as_text=True)
    # CSP 導入に備え、HTML 出力に onclick= は一切残らないこと
    assert "onclick=" not in body
    # 備考モーダルが共通パーシャル経由で描画されている
    assert 'id="remarkModal"' in body
    assert 'id="modalSaveBtn"' in body


def test_worker_html_has_no_inline_onclick(admin_client, app_module):
    """共通入力画面に inline onclick が無い。"""
    resp = admin_client.get("/worker")
    body = resp.get_data(as_text=True)
    assert "onclick=" not in body
    assert 'id="remarkModal"' in body
    assert 'id="modalSaveBtn"' in body


def test_menu_unsubmitted_uses_username(admin_client):
    """V28: メニューの未提出判定は username 基準。翌月分を提出すると警告が消える。"""
    from datetime import datetime, timedelta

    now = datetime.now()
    nd = datetime(now.year, now.month, 1) + timedelta(days=32)
    ny, nm = nd.year, nd.month
    # 提出前: 未提出の警告が出る
    assert "未提出" in admin_client.get("/menu").get_data(as_text=True)
    # 翌月分を提出（開室日が必ず含まれるよう全日 〇 を送る。safe_ym は query から読む）
    data = {f"day_{d}": "〇" for d in range(1, 32)}
    admin_client.post(f"/?year={ny}&month={nm}", data=data)
    # 提出後: 警告が消える
    assert "未提出" not in admin_client.get("/menu").get_data(as_text=True)


def test_month_links_use_japan_time(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "now_jst",
        lambda: datetime(2027, 1, 1, 0, 30, tzinfo=ZoneInfo("Asia/Tokyo")),
    )
    links = app_module.get_month_links()
    assert links == {"now_y": 2027, "now_m": 1, "next_y": 2027, "next_m": 2}


def test_remark_has_client_limit_and_server_truncates(admin_client, app_module):
    body = admin_client.get("/").get_data(as_text=True)
    assert 'maxlength="500"' in body
    admin_client.post(
        "/?year=2026&month=6",
        data={"day_1": "〇", "remark_1": "x" * 600},
    )
    with closing(app_module.get_db()) as conn:
        remark = conn.execute(
            "SELECT remarks FROM shifts WHERE username='admin' AND year=2026 "
            "AND month=6 AND day=1"
        ).fetchone()[0]
    assert len(remark) == 500
