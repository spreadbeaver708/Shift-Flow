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
