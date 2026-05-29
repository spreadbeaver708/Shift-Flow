"""シフト入力フローのテスト（V4, V5, O）。"""

from contextlib import closing


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
    # V25: 備考モーダルが共通パーシャル経由で描画されている
    assert 'id="remarkModal"' in body
    assert 'id="modalSaveBtn"' in body


def test_worker_html_has_no_inline_onclick(admin_client, app_module):
    """V12: worker.html の inline onclick が全廃されている。"""
    # admin の名前で worker ページに入れる
    resp = admin_client.get("/worker/管理者")
    body = resp.get_data(as_text=True)
    assert "onclick=" not in body
    assert 'id="remarkModal"' in body
    assert 'id="modalSaveBtn"' in body
