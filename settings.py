import os
import secrets
from dataclasses import dataclass
from pathlib import Path


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def _integer(name, default, minimum=1, maximum=None):
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} は整数で指定してください（現在: {raw!r}）") from exc
    if value < minimum or (maximum is not None and value > maximum):
        upper = f"〜{maximum}" if maximum is not None else "以上"
        raise RuntimeError(f"{name} は {minimum}{upper}で指定してください（現在: {value}）")
    return value


def _boolean(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise RuntimeError(
        f"{name} は 1/0、true/false、yes/no、on/off のいずれかで指定してください"
        f"（現在: {raw!r}）"
    )


@dataclass(frozen=True)
class Settings:
    app_env: str
    is_prod: bool
    secret_key: str
    trusted_proxy_hops: int
    session_idle_minutes: int
    session_absolute_hours: int
    db_path: str
    trust_cf_connecting_ip: bool
    login_rate_limit: str
    rate_limit_storage_uri: str
    backup_enabled: bool
    daily_backup_keep: int
    monthly_backup_keep: int
    audit_retention: int


def load_settings(instance_path):
    raw_env = os.environ.get("APP_ENV", "development").strip().lower()
    aliases = {"dev": "development", "test": "testing"}
    app_env = aliases.get(raw_env, raw_env)
    if app_env not in {"development", "testing", "production"}:
        raise RuntimeError(
            "APP_ENV は development、testing、production のいずれかで指定してください"
            f"（現在: {raw_env!r}）"
        )
    is_prod = app_env == "production"

    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        if is_prod:
            raise RuntimeError("SECRET_KEY が未設定です（本番では必須）")
        secret_key = secrets.token_hex(32)

    trusted_proxy_hops = _integer("TRUSTED_PROXY_HOPS", 0, minimum=0, maximum=10)
    session_idle_minutes = _integer("SESSION_IDLE_MINUTES", 30, minimum=1, maximum=1440)
    session_absolute_hours = _integer("SESSION_ABSOLUTE_HOURS", 24, minimum=1, maximum=168)

    raw_db_path = os.environ.get("SHIFT_DB_PATH")
    if raw_db_path is not None and not raw_db_path.strip():
        raise RuntimeError("SHIFT_DB_PATH を空にすることはできません")
    if is_prod and raw_db_path is None:
        raise RuntimeError("SHIFT_DB_PATH が未設定です（本番では必須）")
    db_path = (
        raw_db_path.strip()
        if raw_db_path is not None
        else str(Path(instance_path) / "shift.db")
    )
    if is_prod and not os.path.isabs(db_path):
        raise RuntimeError(
            f"SHIFT_DB_PATH は本番では絶対パスで指定してください（現在: {db_path!r}）"
        )

    login_rate_limit = os.environ.get("LOGIN_RATE_LIMIT", "20 per minute").strip()
    if not login_rate_limit:
        raise RuntimeError("LOGIN_RATE_LIMIT を空にすることはできません")
    rate_limit_storage_uri = os.environ.get(
        "RATELIMIT_STORAGE_URI", "memory://"
    ).strip()
    if not rate_limit_storage_uri:
        raise RuntimeError("RATELIMIT_STORAGE_URI を空にすることはできません")

    return Settings(
        app_env=app_env,
        is_prod=is_prod,
        secret_key=secret_key,
        trusted_proxy_hops=trusted_proxy_hops,
        session_idle_minutes=session_idle_minutes,
        session_absolute_hours=session_absolute_hours,
        db_path=db_path,
        trust_cf_connecting_ip=_boolean("TRUST_CF_CONNECTING_IP", False),
        login_rate_limit=login_rate_limit,
        rate_limit_storage_uri=rate_limit_storage_uri,
        backup_enabled=_boolean("BACKUP_ON_STARTUP", is_prod),
        daily_backup_keep=_integer("BACKUP_KEEP", 14, minimum=1, maximum=365),
        monthly_backup_keep=_integer("MONTHLY_BACKUP_KEEP", 12, minimum=1, maximum=120),
        audit_retention=_integer("AUDIT_RETENTION", 10000, minimum=100, maximum=1_000_000),
    )
