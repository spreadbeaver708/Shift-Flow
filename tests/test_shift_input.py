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


def _freeze_jst(app_module, monkeypatch, y=2026, mo=6, d=10):
    """now_jst を固定し、月境界・実行マシンTZに依存しないようにする。"""
    monkeypatch.setattr(
        app_module, "now_jst",
        lambda: datetime(y, mo, d, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )


def test_menu_unsubmitted_uses_username(admin_client, app_module, monkeypatch):
    """メニューの未提出判定は username 基準。当月・翌月の両方を提出すると警告が消える。

    U-3: メニューは当月と翌月の両方の未提出を促す。片方だけ出しても警告は残り、
    両方提出して初めて消える（提出検知が username 基準であることも兼ねて確認）。
    now_jst を 2026-06-10 に固定し当月=6/翌月=7 を確定（月境界・TZ非依存）。
    """
    _freeze_jst(app_module, monkeypatch)
    data = {f"day_{d}": "〇" for d in range(1, 32)}
    # 提出前: 未提出の警告が出る
    assert "未提出" in admin_client.get("/menu").get_data(as_text=True)
    # 翌月(7月)だけ提出 → 当月(6月)が未提出なので警告は残る
    admin_client.post("/?year=2026&month=7", data=data)
    assert "未提出" in admin_client.get("/menu").get_data(as_text=True)
    # 当月(6月)も提出 → 警告が消える
    admin_client.post("/?year=2026&month=6", data=data)
    assert "未提出" not in admin_client.get("/menu").get_data(as_text=True)


def test_menu_worker_link_targets_unsubmitted_month(client, login, app_module, monkeypatch):
    """M-1: 未提出バナーが指す月と「シフト希望を入力」の着地月が一致する。

    旧実装はバナー＝翌月・ボタン＝当月でズレていた。worker リンクに year/month を
    付与し、未提出のうち最も早い月（=当月6月）へ着地することを厳密に固定する。
    """
    _freeze_jst(app_module, monkeypatch)
    login("admin", "Admin-Initial-Passphrase-2026")
    client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "w1", "password": "Worker-Pass-2026!",
            "name": "ワーカー1", "role": "worker", "color": "#e8f5e9",
        },
    )
    login("w1", "Worker-Pass-2026!")
    body = client.get("/menu").get_data(as_text=True)
    assert "未提出" in body
    # 何も提出していない職員 → 着地は最も早い未提出月(=当月6月)に固定される
    assert "/worker?" in body
    assert "month=6" in body
    assert "month=7" not in body  # 翌月ではなく当月へ着地（M-1の核心）


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
