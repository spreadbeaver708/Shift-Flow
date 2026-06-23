import glob
import os
import sqlite3
import threading
import time
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from storage import DatabaseManager


def _manager(path, daily_keep=3, monthly_keep=2):
    return DatabaseManager(
        str(path),
        is_prod=False,
        backup_enabled=False,
        daily_keep=daily_keep,
        monthly_keep=monthly_keep,
    )


def test_pre_migration_backup_is_created(monkeypatch, tmp_path):
    path = tmp_path / "shift.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            "CREATE TABLE users(username TEXT PRIMARY KEY, password TEXT, role TEXT, "
            "name TEXT, is_active INTEGER DEFAULT 1, color TEXT)"
        )
        connection.execute(
            "CREATE TABLE shifts(id INTEGER PRIMARY KEY, year INTEGER, month INTEGER, "
            "day INTEGER, name TEXT, status TEXT, remarks TEXT)"
        )
        connection.execute("INSERT INTO users VALUES ('admin','hash','admin','管理者',1,'#fff')")
        connection.execute("PRAGMA user_version=0")
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    manager = _manager(path)
    manager.ensure_ready()
    backups = glob.glob(str(tmp_path / "backups" / "pre-migration-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with closing(sqlite3.connect(path)) as migrated:
        flag = migrated.execute(
            "SELECT must_change_password FROM users WHERE username='admin'"
        ).fetchone()[0]
    assert flag == 1


def test_daily_and_monthly_backup_retention(monkeypatch, tmp_path):
    path = tmp_path / "shift.db"
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    manager = _manager(path)
    manager.ensure_ready()

    dates = [
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 4, 1, tzinfo=timezone.utc),
    ]
    for current in dates:
        monkeypatch.setattr("storage.now_utc", lambda current=current: current)
        manager.backup("daily")
        manager.backup("monthly")

    daily = glob.glob(str(tmp_path / "backups" / "daily-*.db"))
    monthly = glob.glob(str(tmp_path / "backups" / "monthly-*.db"))
    assert len(daily) == 3
    assert len(monthly) == 2
    assert os.path.basename(sorted(daily)[0]) == "daily-20260201.db"
    assert os.path.basename(sorted(monthly)[0]) == "monthly-202603.db"


def test_backup_writes_are_serialized_and_leave_no_temp_files(
    monkeypatch, tmp_path
):
    path = tmp_path / "shift.db"
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    manager = _manager(path)
    manager.ensure_ready()
    original_copy = manager._copy_database
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def observed_copy(destination):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.02)
            return original_copy(destination)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(manager, "_copy_database", observed_copy)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: manager.backup("manual"), range(4)))

    assert max_active == 1
    assert len(set(results)) == 4
    assert not glob.glob(str(tmp_path / "backups" / "*.tmp-*"))


def test_backup_error_recording_does_not_hide_original_error(
    monkeypatch, tmp_path
):
    path = tmp_path / "shift.db"
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    manager = _manager(path)
    manager.ensure_ready()
    manager.backup_enabled = True

    monkeypatch.setattr(
        manager,
        "backup",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("original backup error")
        ),
    )
    monkeypatch.setattr(
        manager,
        "_set_state",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("state write error")
        ),
    )

    import pytest

    with pytest.raises(RuntimeError, match="original backup error"):
        manager.scheduled_backup(force=True)


def test_status_survives_disk_usage_failure(monkeypatch, tmp_path):
    path = tmp_path / "shift.db"
    monkeypatch.setenv("ADMIN_INIT_PASSWORD", "Admin-Initial-Passphrase-2026")
    manager = _manager(path)
    manager.ensure_ready()
    monkeypatch.setattr(
        "storage.shutil.disk_usage",
        lambda *args: (_ for _ in ()).throw(OSError("unavailable")),
    )
    status = manager.status()
    assert status["disk_free_bytes"] is None
    assert status["disk_free_ratio"] == 1
