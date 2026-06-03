"""DB 初期化と PRAGMA、スキーマのテスト（R, S, V23 マイグレーション）。"""

from contextlib import closing


def test_get_db_applies_wal_pragmas(app_module):
    with closing(app_module.get_db()) as conn:
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert jm.lower() == "wal"
    assert int(sync) == 1  # NORMAL
    assert int(fk) == 1


def test_must_change_password_column_present(app_module):
    """V23: マイグレーションで users.must_change_password 列が追加される。"""
    with closing(app_module.get_db()) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    assert "must_change_password" in cols


def test_initial_admin_marked_must_change_password(app_module):
    """V23: 初期 admin は must_change_password=1。"""
    with closing(app_module.get_db()) as conn:
        row = conn.execute(
            "SELECT must_change_password FROM users WHERE username='admin'"
        ).fetchone()
    assert row[0] == 1


def test_init_db_idempotent(app_module):
    """既存 DB に対して init_db() を再実行しても列追加でクラッシュしない（冪等性）。"""
    # 一度目は app の import で実行済み。二度目を明示的に呼ぶ。
    app_module.init_db()  # 例外が出ないこと
    with closing(app_module.get_db()) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    assert "must_change_password" in cols


def test_v28_tables_and_columns_present(app_module):
    """V28: audit_log / confirmed_shifts テーブルと shifts.username 列が作られる。"""
    with closing(app_module.get_db()) as conn:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        scols = [r[1] for r in conn.execute("PRAGMA table_info(shifts)").fetchall()]
        ccols = [r[1] for r in conn.execute("PRAGMA table_info(confirmed_shifts)").fetchall()]
    assert "audit_log" in names
    assert "confirmed_shifts" in names
    assert "username" in scols
    assert "username" in ccols and "status" in ccols


def test_confirmed_shifts_has_fk_to_users(app_module):
    """V28: confirmed_shifts は users への FK（ON DELETE CASCADE）を持つ。"""
    with closing(app_module.get_db()) as conn:
        fks = conn.execute("PRAGMA foreign_key_list(confirmed_shifts)").fetchall()
    assert fks, "confirmed_shifts に FK が無い"
    # (id, seq, table, from, to, on_update, on_delete, match)
    assert fks[0][2] == "users"
    assert fks[0][6] == "CASCADE"


def test_shifts_username_backfilled_from_legacy(monkeypatch, tmp_path):
    """V28: username 列が無い旧スキーマの既存データを、init_db が name→username に backfill する。"""
    import importlib
    import secrets
    import sqlite3
    import sys

    dbp = tmp_path / "legacy.db"
    con = sqlite3.connect(dbp)
    con.execute(
        "CREATE TABLE shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, "
        "month INTEGER, day INTEGER, name TEXT, status TEXT, remarks TEXT DEFAULT '')"
    )
    con.execute(
        "CREATE TABLE users (username TEXT PRIMARY KEY, password TEXT, role TEXT, "
        "name TEXT, is_active INTEGER DEFAULT 1, color TEXT DEFAULT '#e8f5e9')"
    )
    con.execute("INSERT INTO users VALUES ('leg','x','worker','レガシー',1,'#e8f5e9')")
    con.execute(
        "INSERT INTO shifts (year,month,day,name,status,remarks) "
        "VALUES (2026,6,1,'レガシー','〇','')"
    )
    con.commit()
    con.close()

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(16))
    monkeypatch.setenv("SHIFT_DB_PATH", str(dbp))
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "adminpass1")
    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    sys.modules.pop("app", None)
    mod = importlib.import_module("app")
    try:
        with closing(mod.get_db()) as conn:
            row = conn.execute(
                "SELECT username FROM shifts WHERE name='レガシー'"
            ).fetchone()
        assert row[0] == "leg"
    finally:
        sys.modules.pop("app", None)


def test_backfill_runs_for_existing_null_rows(app_module):
    """V28: 列は存在するが username=NULL の行も、init_db 再実行で backfill される
    （部分移行・ロールバック後・手動投入の取りこぼし防止）。"""
    with closing(app_module.get_db()) as conn, conn:
        conn.execute(
            "INSERT INTO shifts (year, month, day, name, status, remarks, username) "
            "VALUES (2026, 6, 1, '管理者', '〇', '', NULL)"
        )
    app_module.init_db()  # 再実行（列は既に存在）
    with closing(app_module.get_db()) as conn:
        row = conn.execute(
            "SELECT username FROM shifts "
            "WHERE year=2026 AND month=6 AND day=1 AND name='管理者'"
        ).fetchone()
    assert row[0] == "admin"  # name から backfill された
