"""2026-06-25 統合修正プラン（Phase 0〜4）の回帰テスト。

- B2: 追加した弱いパスワードの拒否
- B3: TRUSTED_HOSTS（設定時のみ Host 検証）
- B4: 監査ログ detail に備考本文・パスワードを残さない
- C2: /backup_check で外部保存確認を記録＋監査
- F: 画面名・呼称の統一
- G1: 備考の保存前正規化
"""

import importlib
import secrets
import sys
from contextlib import closing
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from security_utils import is_valid_password, password_error


def _freeze_jst(app_module, monkeypatch, y=2026, mo=6, d=10):
    monkeypatch.setattr(
        app_module, "now_jst",
        lambda: datetime(y, mo, d, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
    )


def _import_app(monkeypatch, tmp_path, **extra):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(tmp_path / "shift.db"))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    mod.app.config["TESTING"] = True
    mod.limiter.enabled = False
    mod.app.config["WTF_CSRF_ENABLED"] = False
    return mod


# ===== B2: 追加した弱いパスワードの拒否 =====


def test_new_weak_passwords_rejected():
    for pw in ["shiftflow2026", "shiftflow2025", "password2026", "admin1234", "shift1234"]:
        assert not is_valid_password(pw), pw
        assert password_error(pw)


def test_reasonable_password_still_accepted():
    assert is_valid_password("Worker-Pass-2026!")


# ===== B3: TRUSTED_HOSTS =====


def test_trusted_hosts_enforced_when_set(monkeypatch, tmp_path):
    mod = _import_app(monkeypatch, tmp_path, TRUSTED_HOSTS="good.example.com")
    try:
        with mod.app.test_client() as c:
            ok = c.get("/login", headers={"Host": "good.example.com"})
            assert ok.status_code == 200
            bad = c.get("/login", headers={"Host": "evil.example.com"})
            assert bad.status_code == 400
    finally:
        sys.modules.pop("app", None)


def test_trusted_hosts_unset_allows_any(monkeypatch, tmp_path):
    mod = _import_app(monkeypatch, tmp_path)
    try:
        assert "TRUSTED_HOSTS" not in mod.app.config or not mod.app.config["TRUSTED_HOSTS"]
        with mod.app.test_client() as c:
            r = c.get("/login", headers={"Host": "anything.example.com"})
            assert r.status_code == 200
    finally:
        sys.modules.pop("app", None)


# ===== B4: 監査ログに秘密情報を残さない =====


def test_audit_detail_excludes_remark_and_password(admin_client, app_module):
    admin_client.post(
        "/?year=2026&month=6",
        data={"day_1": "〇", "remark_1": "SECRET-REMARK-DO-NOT-LOG"},
    )
    with closing(app_module.get_db()) as conn:
        blob = " ".join(
            r[0] or "" for r in conn.execute("SELECT detail FROM audit_log").fetchall()
        )
    assert "SECRET-REMARK-DO-NOT-LOG" not in blob
    assert "Admin-Initial-Passphrase-2026" not in blob
    assert "Admin-Changed-Passphrase-2026" not in blob


# ===== C2: 外部保存の確認記録 =====


def test_backup_check_records_and_audits(admin_client, app_module):
    before = app_module.db_manager.state().get("last_external_backup_checked", "")
    resp = admin_client.post("/backup_check", follow_redirects=False)
    assert resp.status_code == 302
    after = app_module.db_manager.state().get("last_external_backup_checked", "")
    assert after and after != before
    with closing(app_module.get_db()) as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='backup_check'"
        ).fetchone()[0]
    assert n == 1


# ===== G1: 備考の保存前正規化 =====


def test_normalize_remark_strips_control_and_collapses_newlines(app_module):
    out = app_module.normalize_remark("a\r\n\n\n\nb")
    assert out == "a\n\nb"
    cleaned = app_module.normalize_remark("08:00\x07\x00開始\x08")
    assert "\x07" not in cleaned and "\x00" not in cleaned and "\x08" not in cleaned
    assert "08:00" in cleaned and "開始" in cleaned
    # 改行・タブは残す
    assert app_module.normalize_remark("a\tb\nc") == "a\tb\nc"


def test_remark_normalized_on_save(admin_client, app_module):
    admin_client.post(
        "/?year=2026&month=6",
        data={"day_1": "〇", "remark_1": "16:00\x07開始\x00"},
    )
    with closing(app_module.get_db()) as conn:
        remark = conn.execute(
            "SELECT remarks FROM shifts WHERE username='admin' AND year=2026 "
            "AND month=6 AND day=1"
        ).fetchone()[0]
    assert "\x07" not in remark and "\x00" not in remark
    assert "16:00" in remark and "開始" in remark


def test_backup_check_requires_admin(admin_client):
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create", "username": "w2",
            "password": "Worker-Pass-2026!", "name": "ワーカー2",
            "role": "worker", "color": "#e8f5e9",
        },
    )
    admin_client.post("/logout")
    admin_client.post("/login", data={"username": "w2", "password": "Worker-Pass-2026!"})
    resp = admin_client.post("/backup_check", follow_redirects=False)
    assert resp.status_code == 403


# ===== B4: _serialize_detail のJSON化・切り詰め =====


def test_serialize_detail_dict_and_truncation(app_module):
    sd = app_module._serialize_detail
    assert sd({"name": "太郎", "ok": 3}) == '{"name": "太郎", "ok": 3}'
    assert sd("x" * 600) == "x" * app_module._AUDIT_DETAIL_MAX
    assert sd("short") == "short"


# ===== C2: 外部保存確認の期限切れ判定 =====


def test_is_external_check_overdue_boundaries(app_module):
    f = app_module._is_external_check_overdue
    assert f("") is True
    assert f(None) is True
    assert f("not-a-date") is True
    now = app_module.now_utc()
    assert f(now.isoformat(timespec="seconds")) is False
    assert f((now - timedelta(days=30)).isoformat(timespec="seconds")) is False
    assert f((now - timedelta(days=40)).isoformat(timespec="seconds")) is True


# ===== G1: 正規化→切り詰めの順序 =====


def test_normalize_remark_strips_then_truncates(app_module):
    # 制御文字を除去してから[:500]。切り詰めを先にすると len<500 になり落ちる
    out = app_module.normalize_remark(("\x07" * 200) + ("x" * 600))
    assert out == "x" * 500


# ===== B3: TRUSTED_HOSTS とヘルスチェック =====


def test_trusted_hosts_does_not_lock_out_healthchecks(monkeypatch, tmp_path):
    """設定時、正しいHostなら /healthz は通り、別Hostは400（公開ホスト名を含める必要がある）。"""
    mod = _import_app(monkeypatch, tmp_path, TRUSTED_HOSTS="good.example.com")
    try:
        with mod.app.test_client() as c:
            assert c.get("/healthz", headers={"Host": "good.example.com"}).status_code == 200
            assert c.get("/healthz", headers={"Host": "evil.example.com"}).status_code == 400
    finally:
        sys.modules.pop("app", None)


# ===== C3/O-1: 成功GETでバックアップ起動、static/healthzは除外 =====


def test_after_request_backup_trigger_excludes_static_and_health(admin_client, app_module, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "BACKUP_ON_STARTUP", True)
    monkeypatch.setattr(
        app_module.db_manager, "scheduled_backup", lambda *a, **k: calls.append(1)
    )
    admin_client.get("/menu")
    assert len(calls) >= 1
    n = len(calls)
    # healthz / readyz は除外集合 {"static","healthz","readyz"} に属し起動しない
    admin_client.get("/healthz")
    assert len(calls) == n
    admin_client.get("/readyz")
    assert len(calls) == n


# ===== U1: 全休と未提出の出し分け =====


def test_submissions_distinguishes_all_off_from_unsubmitted(admin_client):
    # admin 自身は全休(day_*無し→全て×)で提出 → submitted=True, ok=0
    admin_client.post("/?year=2026&month=6")
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create", "username": "w4",
            "password": "Worker-Pass-2026!", "name": "ワーカー4",
            "role": "worker", "color": "#e8f5e9",
        },
    )
    body = admin_client.get("/submissions?year=2026&month=6").get_data(as_text=True)
    assert "0（全休?）" in body  # admin: 全休提出
    assert "—" in body           # w4: 未提出


# ===== F1: リライトした画面名・flash文言の固定 =====


def test_flash_wording_pins(admin_client):
    body = admin_client.get("/staff/nonexistent?year=2026&month=6", follow_redirects=True).get_data(as_text=True)
    assert "職員が見つかりません" in body
    body2 = admin_client.get("/confirm", follow_redirects=True).get_data(as_text=True)
    assert "提出状況・締め切り" in body2


# ===== H2: safe_ym(args) と resolve_ym(values) の source差 =====


def test_safe_ym_reads_args_resolve_ym_reads_values(app_module):
    app = app_module.app
    with app.test_request_context("/admin", method="POST", data={"year": "2026", "month": "9"}):
        # クエリ無し・フォームのみ: safe_ym は args 限定 → 既定へフォールバック
        assert app_module.safe_ym(2026, 6) == (2026, 6)
        # resolve_ym は values(args+form) → フォーム値を拾う
        assert app_module.resolve_ym(2026, 6) == (2026, 9)


# ===== menu: 締切後の月は職員に促さない / 管理者はロック対象外 =====


def test_menu_hides_locked_month_for_staff_not_admin(admin_client, app_module, monkeypatch):
    _freeze_jst(app_module, monkeypatch, y=2026, mo=6, d=20)
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create", "username": "w5",
            "password": "Worker-Pass-2026!", "name": "ワーカー5",
            "role": "worker", "color": "#e8f5e9",
        },
    )
    # 当月(6月)の締切を過去日(6/1)に設定 → 職員は6月ロック、管理者はロック対象外
    admin_client.post("/deadline", data={"year": "2026", "month": "6", "deadline": "2026-06-01"})
    # 管理者メニュー: 6月も未提出として残る
    assert "未提出" in admin_client.get("/menu").get_data(as_text=True)
    # 職員メニュー: 6月はロックで除外 → 着地は7月（6月へは促さない）
    worker_c = admin_client.application.test_client()
    worker_c.post("/login", data={"username": "w5", "password": "Worker-Pass-2026!"})
    body = worker_c.get("/menu").get_data(as_text=True)
    assert "month=7" in body
    assert "month=6" not in body
