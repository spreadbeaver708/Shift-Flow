import glob
import os
import shutil
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

from security_utils import (
    generate_temporary_password,
    is_valid_password,
    normalize_password,
)
from time_utils import now_utc


SCHEMA_VERSION = 31


class DatabaseManager:
    def __init__(
        self,
        path,
        *,
        is_prod,
        backup_enabled,
        daily_keep,
        monthly_keep,
    ):
        self.path = path
        self.is_prod = is_prod
        self.backup_enabled = backup_enabled
        self.daily_keep = daily_keep
        self.monthly_keep = monthly_keep
        self._ready = False
        self._lock = threading.Lock()
        self._backup_lock = threading.RLock()

    @property
    def backup_dir(self):
        return str(Path(self.path).parent / "backups")

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _raw_connect(self, path=None):
        return sqlite3.connect(path or self.path, timeout=30)

    def _schema_version(self):
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            return 0
        with closing(self._raw_connect()) as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def _copy_database(self, destination):
        os.makedirs(self.backup_dir, exist_ok=True)
        temporary = (
            f"{destination}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        try:
            with closing(self._raw_connect()) as src, closing(
                self._raw_connect(temporary)
            ) as dst:
                src.backup(dst)
            with closing(self._raw_connect(temporary)) as check:
                result = check.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(
                    f"バックアップの健全性確認に失敗しました: {result}"
                )
            os.replace(temporary, destination)
        except Exception:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        return destination

    def backup(self, kind="manual", *, old_version=None):
        with self._backup_lock:
            timestamp = now_utc()
            if kind == "daily":
                name = f"daily-{timestamp:%Y%m%d}.db"
            elif kind == "monthly":
                name = f"monthly-{timestamp:%Y%m}.db"
            elif kind == "pre-migration":
                name = (
                    f"pre-migration-v{old_version or 0}-to-v{SCHEMA_VERSION}-"
                    f"{timestamp:%Y%m%d-%H%M%S-%f}.db"
                )
            else:
                name = f"manual-{timestamp:%Y%m%d-%H%M%S-%f}.db"
            destination = os.path.join(self.backup_dir, name)
            if kind in {"daily", "monthly"} and os.path.exists(destination):
                return destination
            result = self._copy_database(destination)
            if kind in {"daily", "monthly"}:
                self._prune(
                    kind,
                    self.daily_keep if kind == "daily" else self.monthly_keep,
                )
            return result

    def _prune(self, prefix, keep):
        pattern = os.path.join(self.backup_dir, f"{prefix}-*.db")
        for old in sorted(glob.glob(pattern))[:-keep]:
            try:
                os.remove(old)
            except OSError:
                pass

    def _set_state(self, key, value):
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "INSERT INTO app_state(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def state(self):
        with closing(self.connect()) as conn:
            rows = conn.execute("SELECT key, value FROM app_state").fetchall()
        return dict(rows)

    def record_external_backup_check(self):
        """管理者が『月次の外部保存を確認した』ことを記録する（管理メニューのボタンから）。

        同一ディスク内バックアップは災害に弱いため、月次で外部退避したかを画面で追える
        ようにする。記録は app_state に残し、status() 経由でメニューに表示・警告する。
        """
        self._set_state(
            "last_external_backup_checked",
            now_utc().isoformat(timespec="seconds"),
        )

    def status(self):
        state = self.state()
        try:
            usage = shutil.disk_usage(Path(self.path).parent)
        except OSError:
            state["disk_free_bytes"] = None
            state["disk_free_ratio"] = 1
        else:
            state["disk_free_bytes"] = usage.free
            state["disk_free_ratio"] = usage.free / usage.total if usage.total else 0
        return state

    def _scheduled_backup_due(self):
        state = self.state()
        raw = state.get("last_backup_success")
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(raw)
        except ValueError:
            return True
        return now_utc() - last >= timedelta(hours=24)

    def scheduled_backup(self, force=False):
        if not self.backup_enabled:
            return None
        with self._backup_lock:
            if not force and not self._scheduled_backup_due():
                return None
            try:
                daily = self.backup("daily")
                self.backup("monthly")
                self._set_state(
                    "last_backup_success",
                    now_utc().isoformat(timespec="seconds"),
                )
                self._set_state("last_backup_path", daily)
                self._set_state("last_backup_error", "")
                return daily
            except Exception as exc:
                try:
                    self._set_state("last_backup_error", str(exc)[:500])
                except Exception:
                    pass
                raise

    def ensure_ready(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            existed = os.path.exists(self.path) and os.path.getsize(self.path) > 0
            old_version = self._schema_version()
            if existed and old_version < SCHEMA_VERSION:
                self.backup("pre-migration", old_version=old_version)
            self._initialize_schema(previous_version=old_version if existed else SCHEMA_VERSION)
            if self.backup_enabled:
                try:
                    self.scheduled_backup()
                except Exception as exc:
                    print(f"[backup] 自動バックアップ失敗: {exc}")
            self._ready = True

    def reconcile_schema(self):
        self.ensure_ready()
        self._initialize_schema()

    def _initialize_schema(self, previous_version=SCHEMA_VERSION):
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS shifts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "year INTEGER, month INTEGER, day INTEGER, "
                "name TEXT, status TEXT, remarks TEXT DEFAULT '')"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "username TEXT PRIMARY KEY, password TEXT, role TEXT, "
                "name TEXT, is_active INTEGER DEFAULT 1, color TEXT DEFAULT '#e8f5e9')"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS audit_log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts TEXT, actor TEXT, actor_name TEXT, action TEXT, "
                "target TEXT, detail TEXT, ip TEXT)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS app_state ("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')"
            )
            # 締め切り（年月ごとに1件）。この日からスタッフは希望を変更できない。
            conn.execute(
                "CREATE TABLE IF NOT EXISTS deadlines ("
                "year INTEGER, month INTEGER, deadline TEXT, "
                "PRIMARY KEY (year, month))"
            )

            # must_change_password 列は互換のため残すが、初回強制変更は廃止済み。
            user_columns = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
            if "must_change_password" not in user_columns:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0"
                )
            if previous_version < SCHEMA_VERSION:
                # 強制変更を廃止したため、過去に立った強制フラグを一括で寝かせる。
                conn.execute("UPDATE users SET must_change_password=0")

            shift_columns = [row[1] for row in conn.execute("PRAGMA table_info(shifts)")]
            if "username" not in shift_columns:
                conn.execute("ALTER TABLE shifts ADD COLUMN username TEXT")
            conn.execute(
                "UPDATE shifts SET username="
                "(SELECT u.username FROM users u WHERE u.name = shifts.name) "
                "WHERE username IS NULL"
            )

            # 確定シフト（confirmed_shifts）は廃止。既存DBのテーブルは非破壊で温存し、
            # ここでは新規作成・参照しない（締め切り後の shifts を最終予定として扱う）。

            duplicate_names = conn.execute(
                "SELECT COUNT(*) FROM ("
                "SELECT 1 FROM users GROUP BY name HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            if duplicate_names:
                raise RuntimeError(
                    f"users.name に重複が {duplicate_names} 件あります。"
                    "バックアップを確認し、重複を解消してから再起動してください"
                )
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name ON users(name)")

            exists = conn.execute(
                "SELECT 1 FROM users WHERE username='admin'"
            ).fetchone()
            if not exists:
                initial = os.environ.get("ADMIN_INIT_PASSWORD")
                generated = False
                if not initial:
                    if self.is_prod:
                        raise RuntimeError(
                            "初回起動時は ADMIN_INIT_PASSWORD を設定してください"
                        )
                    initial = generate_temporary_password()
                    generated = True
                if not is_valid_password(initial, "admin"):
                    raise RuntimeError(
                        "ADMIN_INIT_PASSWORD は8〜128文字で、"
                        "推測されにくい値を指定してください"
                    )
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO users "
                    "(username, password, role, name, is_active, color, must_change_password) "
                    "VALUES (?, ?, ?, ?, 1, ?, 0)",
                    (
                        "admin",
                        generate_password_hash(normalize_password(initial)),
                        "admin",
                        "管理者",
                        "#2196F3",
                    ),
                )
                if cursor.rowcount > 0 and generated:
                    print("[dev] admin 初期パスワードを一度だけ表示します:")
                    print(initial)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def ready_check(self):
        self.ensure_ready()
        required = {"users", "shifts", "deadlines", "audit_log", "app_state"}
        with closing(self.connect()) as conn:
            conn.execute("SELECT 1").fetchone()
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        return required <= tables
