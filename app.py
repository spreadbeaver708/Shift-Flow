import os
import re
import json
import glob
import secrets
import sqlite3
import calendar
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort,
)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

# =====================
# アプリ初期設定
# =====================
app = Flask(__name__)

APP_ENV = os.environ.get("APP_ENV", "development")
IS_PROD = APP_ENV == "production"

# Codex(後追加)#4: リバプロ配下では request.remote_addr がプロキシ IP（127.0.0.1 等）になり、
# レート制限が全ユーザーで共有されてしまう。TRUSTED_PROXY_HOPS で信頼するプロキシ段数を
# 明示した時のみ ProxyFix を適用し、X-Forwarded-For 等から実 IP を取り出す。
# 直接公開（プロキシ無し）の場合は 0 のまま（X-Forwarded-* を信頼するとIP偽装可能なため）。
#
# Codex(再指摘)#4: 不正値（abc / 空文字 / 負数）は ValueError のまま放置せず、
# 明示メッセージ付き RuntimeError で fail-fast する。
# 「安全に 0 倒し」だとリバプロ配下で気づかずレート制限共有のまま動く事故源になるため、
# 設定ミスを早期に検出する fail-fast を選択。
_hops_raw = os.environ.get("TRUSTED_PROXY_HOPS", "0").strip()
try:
    TRUSTED_PROXY_HOPS = int(_hops_raw)
except ValueError:
    raise RuntimeError(
        f"TRUSTED_PROXY_HOPS は非負整数で指定してください（現在: {_hops_raw!r}）。"
        " 既定 0、Caddy/Nginx 経由なら 1。"
    )
if TRUSTED_PROXY_HOPS < 0:
    raise RuntimeError(
        f"TRUSTED_PROXY_HOPS は 0 以上で指定してください（現在: {TRUSTED_PROXY_HOPS}）"
    )

# B: SECRET_KEY は本番では必須（fail-fast）。開発ではランダムフォールバック。
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if IS_PROD:
        raise RuntimeError("SECRET_KEY が未設定です（本番では必須）")
    SECRET_KEY = secrets.token_hex(32)
    print("[dev] SECRET_KEY 未設定のためランダム鍵を生成（開発限定）")
app.secret_key = SECRET_KEY

# V28: アイドルタイムアウト（無操作で自動ログアウト）。個人端末の置き忘れ対策。
# SESSION_REFRESH_EACH_REQUEST 既定 True によりリクエストごとに有効期限が延びる
# （スライディング）。不正値は fail-fast（TRUSTED_PROXY_HOPS と同じ方針）。
_idle_raw = os.environ.get("SESSION_IDLE_MINUTES", "30").strip()
try:
    SESSION_IDLE_MINUTES = int(_idle_raw)
except ValueError:
    raise RuntimeError(
        f"SESSION_IDLE_MINUTES は正の整数で指定してください（現在: {_idle_raw!r}）"
    )
if SESSION_IDLE_MINUTES < 1:
    raise RuntimeError(
        f"SESSION_IDLE_MINUTES は 1 以上で指定してください（現在: {SESSION_IDLE_MINUTES}）"
    )

# H: セッションCookie属性。SECURE は HTTPS本番限定。
# V28: SESSION_COOKIE_NAME を既定の "session" から変更（フレームワーク指紋の低減）。
#      PERMANENT_SESSION_LIFETIME はアイドルタイムアウトの上限。
app.config.update(
    SESSION_COOKIE_SECURE=IS_PROD,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # V29: 本番(HTTPS)は __Host- prefix で固定（Secure/Path=/・Domain無が条件）。
    #      dev は HTTP のため通常名（__Host- は Secure 必須で HTTP 不可）。
    SESSION_COOKIE_NAME=("__Host-sfid" if IS_PROD else "sfid"),
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=SESSION_IDLE_MINUTES),
    # V29: 本文サイズ上限。Werkzeug の form 既定(500KB/1000parts)に加え、本文全体を
    #      早期に総量で弾く深層防御（フォームは数十KB）。超過は 413。
    MAX_CONTENT_LENGTH=256 * 1024,
)

# Codex(後追加)#4: ProxyFix を信頼段数分だけ適用（既定 0 では適用しない）
if TRUSTED_PROXY_HOPS > 0:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_HOPS,
        x_proto=TRUSTED_PROXY_HOPS,
        x_host=TRUSTED_PROXY_HOPS,
    )

# D: CSRF
csrf = CSRFProtect(app)

# V29: クライアントIP解決。前段が Cloudflare + Render LB のため get_remote_address() は
# 既定でプロキシIPになりうる。Render は CF-Connecting-IP（元クライアントIPのみ）を転送するので、
# 明示的に信頼する場合（env TRUST_CF_CONNECTING_IP=1）に限りそれを優先する。
# 直アクセス不可（エッジ経由のみ）な構成でのみ安全＝TRUSTED_PROXY_HOPS と同じ明示信頼方針。
TRUST_CF_CONNECTING_IP = os.environ.get("TRUST_CF_CONNECTING_IP", "0").strip().lower() in ("1", "true", "yes")


def client_ip():
    if TRUST_CF_CONNECTING_IP:
        cf = request.headers.get("CF-Connecting-IP")
        if cf:
            return cf.split(",")[0].strip()[:64]
    return get_remote_address()


# I: ログイン試行レート制限（key は client_ip に統一）
# Codex#4: storage_uri を明示。複数 worker で厳密共有したい場合は RATELIMIT_STORAGE_URI=redis://...。
# 未指定（memory://）は worker ごとに別カウンタになる点に注意（README 参照）。
# V29: ログイン上限は LOGIN_RATE_LIMIT で可変（既定 20/分）。change_password は 10/分維持。
LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "20 per minute")
limiter = Limiter(
    client_ip,
    app=app,
    default_limits=[],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)

# S: DBパスはCWDに依存させない。SHIFT_DB_PATH があればそちら、無ければ instance_path/shift.db
# Codex#3: 本番では絶対パス必須（相対パスは gunicorn 起動位置によって別 DB を作る事故源）
DB_PATH = os.environ.get("SHIFT_DB_PATH") or os.path.join(app.instance_path, "shift.db")
if IS_PROD and not os.path.isabs(DB_PATH):
    raise RuntimeError(
        f"SHIFT_DB_PATH は本番では絶対パスで指定してください（現在: {DB_PATH!r}）"
    )
os.makedirs(app.instance_path, exist_ok=True)
# instance_path 以外を指定された場合も格納ディレクトリは作成しておく
_db_dir = os.path.dirname(DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

# V29: 起動時自動バックアップの設定（実行は既定で本番のみ。テスト/開発では走らせない）。
try:
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))
except ValueError:
    BACKUP_KEEP = 14
BACKUP_ON_STARTUP = os.environ.get(
    "BACKUP_ON_STARTUP", "1" if IS_PROD else "0"
).strip().lower() in ("1", "true", "yes")

# カレンダーを日曜日始まりに固定
calendar.setfirstweekday(calendar.SUNDAY)


def get_db():
    # R: SQLite 同時書き込み堅牢化（フェーズ2 本格対応）
    #   - timeout=30:          ロック待ち（既定 5 秒 → 30 秒）。
    #   - journal_mode=WAL:    読み書きの並行性を上げる。スマホ同時提出での「database is locked」予防。
    #   - synchronous=NORMAL:  WAL での既定。性能と耐久性のバランス。
    #   - foreign_keys=ON:     将来の FK 制約（フェーズ3 で user_id 化する際に効く）。
    #   journal_mode は DB ファイル単位で永続化される PRAGMA だが、毎回適用しても害はない。
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# =====================
# データベース初期化
# =====================
def init_db():
    with closing(get_db()) as conn, conn:
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

        # V28: 監査ログ（操作ログ）。意図的に users への FK は張らない
        #   - ユーザーを物理削除しても「誰が何をしたか」の記録は残すべき
        #   - login_fail の未知 ID や 'anonymous' も記録するため
        conn.execute(
            "CREATE TABLE IF NOT EXISTS audit_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts TEXT, actor TEXT, actor_name TEXT, action TEXT, "
            "target TEXT, detail TEXT, ip TEXT)"
        )

        # V23: must_change_password 列を冪等に追加（既存 DB / 新規 DB どちらでも安全）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "must_change_password" not in cols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0"
            )

        # V28: シフトを表示名から username 基準へ非破壊移行（rename の取りこぼし解消）。
        #   - username 列を冪等追加し、既存行は users.name から backfill。
        #   - name 列は互換＆ロールバック用に残し、以後 INSERT 時に併記する。
        scols = [r[1] for r in conn.execute("PRAGMA table_info(shifts)").fetchall()]
        if "username" not in scols:
            conn.execute("ALTER TABLE shifts ADD COLUMN username TEXT")
        # backfill は「列追加直後」だけでなく **毎回** 実行する（冪等）。
        # 部分移行・旧版へのロールバック後の再起動・CLI 手動投入などで生じた
        # username IS NULL の行を取りこぼすと /admin・/submissions から希望が消えるため。
        conn.execute(
            "UPDATE shifts SET username="
            "(SELECT u.username FROM users u WHERE u.name = shifts.name) "
            "WHERE username IS NULL"
        )

        # V28: 確定シフト（管理者が作成、職員はチーム全体を読み取り専用で閲覧）。
        #   username 基準。新規テーブルなので CREATE 時に FK を付与できる（既設 foreign_keys=ON）。
        #   ON DELETE CASCADE: ユーザー物理削除時に確定行も自動削除（CLI 運用を阻害しない）。
        conn.execute(
            "CREATE TABLE IF NOT EXISTS confirmed_shifts ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "year INTEGER, month INTEGER, day INTEGER, "
            "username TEXT, status TEXT, "
            "UNIQUE(year, month, day, username), "
            "FOREIGN KEY(username) REFERENCES users(username) ON DELETE CASCADE)"
        )

        # V29: 表示名のDB一意制約（アプリ検証の二重化）。既存重複があると索引作成に失敗し
        # 起動不能になるため、重複0件のときだけ作成する（重複時は警告printしてスキップ）。
        dup_names = conn.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM users GROUP BY name HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        if dup_names == 0:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name ON users(name)")
        else:
            print(f"[init] users.name に重複 {dup_names} 件のため UNIQUE 索引はスキップ（要手動解消）")

        # C: 旧版の固定初期パスワードを排除。admin が存在しない場合のみ作成。
        # Codex#2: gunicorn -w N で複数 worker が同時に起動した場合の競合を防ぐため
        #   1) INSERT OR IGNORE で冪等にする（UNIQUE 違反は無視）
        #   2) 実際に書き込みに成功した worker のみログ表示する（rowcount > 0）
        exists = conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone()
        if not exists:
            init_pw = os.environ.get("ADMIN_INIT_PASSWORD")
            is_random = False
            if not init_pw:
                init_pw = secrets.token_urlsafe(12)
                is_random = True
            cur = conn.execute(
                "INSERT OR IGNORE INTO users "
                "(username, password, role, name, is_active, color, must_change_password) "
                "VALUES (?, ?, ?, ?, 1, ?, 1)",
                ("admin", generate_password_hash(init_pw), "admin", "管理者", "#2196F3"),
            )
            if cur.rowcount > 0 and is_random:
                print("[init] ADMIN_INIT_PASSWORD 未設定のためランダム生成しました。")
                print(f"[init] admin 初期パスワード（一度だけ表示）: {init_pw}")
                print("[init] 初回ログイン後、/change_password で必ず変更してください。")
            elif cur.rowcount > 0:
                print("[init] admin ユーザーを作成しました（ADMIN_INIT_PASSWORD を使用）")


def backup_db():
    """DB を backups/ に SQLite Backup API でコピーし、最新 BACKUP_KEEP 世代を残す。
    起動を止めないため、呼び出し側で例外を握りつぶす想定。生成先パスを返す。"""
    bdir = os.path.join(_db_dir or ".", "backups")
    os.makedirs(bdir, exist_ok=True)
    # マイクロ秒まで含め、同一秒内の連続実行でもファイル名が衝突しないようにする
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    dest = os.path.join(bdir, f"shift-{ts}.db")
    with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(dest)) as dst:
        src.backup(dst)  # オンライン整合バックアップ（稼働中でも安全）
    # 古い世代を削除（ファイル名は時刻順＝辞書順）
    if BACKUP_KEEP > 0:
        for old in sorted(glob.glob(os.path.join(bdir, "shift-*.db")))[:-BACKUP_KEEP]:
            try:
                os.remove(old)
            except OSError:
                pass
    return dest


init_db()
print(f"[init] DB_PATH={DB_PATH}")
# V29: 起動時自動バックアップ（既定で本番のみ）。失敗しても起動は止めない。
if BACKUP_ON_STARTUP:
    try:
        print(f"[init] startup backup: {backup_db()}")
    except Exception as e:
        print(f"[init] startup backup skipped (error: {e})")


# =====================
# 入力検証ヘルパー
# =====================
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,32}$")
# Codex(後追加)#3: 表示名は URL パス（/worker/<name>）に入るため URL 予約文字を禁止する。
# 加えて HTML / 制御文字面で問題になりがちな文字も弾く。
NAME_FORBIDDEN_RE = re.compile(r"[/\\?#&<>\r\n\t\x00]")
REMARK_MAX_LEN = 500


def get_month_links():
    now = datetime.now()
    next_date = datetime(now.year, now.month, 1) + timedelta(days=32)
    return {
        "now_y": now.year, "now_m": now.month,
        "next_y": next_date.year, "next_m": next_date.month,
    }


# V27: パスワード方針（NIST SP 800-63B の考え方）。
#   - 長さを重視し 8 文字以上。記号・空白・日本語も許可し、文字種の縛りはかけない
#     （以前の .isalnum() 必須は、強い記号入りパスワードを弾く逆効果だった）。
#   - 上限 128 文字（極端に長い入力でハッシュ計算資源を浪費させる事故を防ぐ）。
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 128


def is_valid_password(p):
    return p is not None and PASSWORD_MIN_LEN <= len(p) <= PASSWORD_MAX_LEN


def safe_ym(default_y, default_m):
    # O: year/month の範囲検証
    y = request.args.get("year", default_y, type=int)
    m = request.args.get("month", default_m, type=int)
    if not isinstance(m, int) or not (1 <= m <= 12):
        m = default_m
    if not isinstance(y, int) or not (2000 <= y <= 2100):
        y = default_y
    return y, m


# =====================
# Q: 各リクエストで DB からユーザー状態を再取得
# =====================
@app.before_request
def load_current_user():
    # V28: CSP nonce を毎リクエスト生成。static・エラーページを含む全レスポンスで
    # ヘッダとテンプレートの nonce を一致させるため、最初に必ず設定する。
    g.csp_nonce = secrets.token_urlsafe(16)
    g.user = None
    # 静的ファイルは認証不要。毎リクエストの DB 照会を避ける（負荷・攻撃面の低減）。
    if request.endpoint == "static":
        return
    u = session.get("username")
    if not u:
        return
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT username, role, name, is_active, must_change_password "
            "FROM users WHERE username=?",
            (u,),
        ).fetchone()
    if not row or row[3] == 0:
        # 削除または停止済み → 旧セッションを破棄
        session.clear()
        return
    g.user = SimpleNamespace(
        username=row[0], role=row[1], name=row[2],
        must_change_password=bool(row[4]),
    )


# V23: 初回ログインや管理者リセット後は、パスワード変更まで他画面に進めない
ALLOWED_WHEN_MUST_CHANGE = {"change_password", "logout", "static", "help_page"}


@app.before_request
def force_password_change():
    if (
        g.user
        and g.user.must_change_password
        and request.endpoint not in ALLOWED_WHEN_MUST_CHANGE
    ):
        return redirect(url_for("change_password"))


@app.context_processor
def inject_current_user():
    # テンプレも session['role'] ではなく current_user.role を使うように統一
    # V28: 全テンプレの <script nonce="..."> 用に csp_nonce も渡す
    return {
        "current_user": getattr(g, "user", None),
        "csp_nonce": getattr(g, "csp_nonce", ""),
    }


# V2: CSRF トークン期限切れ時の親切な UX 救済
# 既定の 400 ページに着地すると「シフトを出したつもりが消えた」事故になるため、
# セッションを破棄しログイン画面に flash 付きで送る。
# 重要: flash() は内部で session を使うため session.clear() → flash() → redirect() の順。
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    # V28: セッション破棄の前に記録（actor は g.user か anonymous）
    log_event("csrf_error", target=(request.path or "")[:128])
    session.clear()
    flash("セッションが切れました。もう一度ログインしてください。")
    return redirect(url_for("login"))


# V9/V27/V28: セキュリティヘッダ。
#   - CSP: 外部リソース読み込み・フレーム埋め込み・フォーム送信先の外部流出を遮断。
#     script は nonce 方式（'unsafe-inline' を撤去）＝ XSS 時の inline スクリプト実行を遮断。
#     style は inline 属性（style="..."）を多用するため当面 'unsafe-inline' を許可
#     （nonce は inline style 属性に効かず、撤去は全テンプレの CSS 化が必要なため別タスク）。
#     base-uri は 'none'（<base> 注入の遮断）。外部 CDN は未使用。
#   - HSTS: 本番（HTTPS）でのみ付与。HTTP への降格を防ぐ。
def _build_csp(nonce):
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )


@app.after_request
def add_security_headers(resp):
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault(
        "Content-Security-Policy", _build_csp(getattr(g, "csp_nonce", ""))
    )
    if IS_PROD:
        resp.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    # V28/V29: 静的以外の全動的応答を端末・中間キャッシュに残さない（共有/個人端末の戻るボタン
    # 対策、login の CSRF トークン鮮度、CVE-2026-27205 = session アクセス時の Vary: Cookie 欠落緩和）。
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    return resp


# V14: カスタムエラーページ。スタックトレースの露出を防ぎ、職員が迷子にならないように
# メニュー / ログインへの導線を提示する。
@app.errorhandler(403)
def handle_403(e):
    return render_template("errors/403.html"), 403


@app.errorhandler(404)
def handle_404(e):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def handle_500(e):
    return render_template("errors/500.html"), 500


@app.errorhandler(413)
def handle_413(e):
    # V29: 本文サイズ超過。素のエラーを出さず親切ページへ。
    return render_template("errors/413.html"), 413


def require_login():
    return g.user is not None


def require_admin():
    return g.user is not None and g.user.role == "admin"


# V27: ログイン失敗時、ユーザーの存在有無で応答時間が変わると ID 列挙の手がかりになる。
# 該当ユーザーが無い場合もこのダミーハッシュで検証を回し、処理時間を平準化する。
_DUMMY_PW_HASH = generate_password_hash("not-a-real-password")


# =====================
# V28: 監査ログ（操作ログ）
# =====================
# 肥大化防止のため最新 N 件だけ保持する。
AUDIT_RETENTION = int(os.environ.get("AUDIT_RETENTION", "10000"))
_AUDIT_DETAIL_MAX = 500


def log_action(conn, action, target="", detail="", actor=None, actor_name=None):
    """監査ログを 1 行追加する（呼び出し側のトランザクション conn 内で実行）。

    actor/actor_name 省略時は g.user から取得（未ログインは 'anonymous'）＝サーバ権威。
    禁止: パスワード/ハッシュ/セッション値/備考(remark)本文/CSRF トークンは detail に入れない。
    detail は dict なら JSON 文字列化し、長さ上限で truncate する。
    """
    if actor is None:
        u = getattr(g, "user", None)
        actor = u.username if u else "anonymous"
        actor_name = u.name if u else ""
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    try:
        ip = client_ip() or ""
    except Exception:
        ip = ""
    conn.execute(
        "INSERT INTO audit_log (ts, actor, actor_name, action, target, detail, ip) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            (actor or "")[:64],
            (actor_name or "")[:64],
            (action or "")[:32],
            (target or "")[:128],
            detail[:_AUDIT_DETAIL_MAX],
            (ip or "")[:64],
        ),
    )
    # 保全: id は単調増加なので「最新 N 件の窓」より古い行を削除（PK インデックスで安価）
    conn.execute(
        "DELETE FROM audit_log WHERE id <= (SELECT MAX(id) - ? FROM audit_log)",
        (AUDIT_RETENTION,),
    )


def log_event(action, target="", detail="", actor=None, actor_name=None):
    """周囲にトランザクションが無い箇所（login/logout/CSRF）向けの簡易版。"""
    with closing(get_db()) as conn, conn:
        log_action(conn, action, target, detail, actor, actor_name)


# V29: 管理者専用ルートの共通ガード（認可を一貫させる）。
#   未ログイン      → login へリダイレクト（呼び出し側で return する）
#   ログイン済み非管理者 → authz_fail を監査記録して 403（abort で送出）
#   管理者          → None（呼び出し側は処理続行）
def deny_if_not_admin():
    if not require_login():
        return redirect(url_for("login"))
    if not require_admin():
        log_event("authz_fail", target=(request.path or "")[:128])
        abort(403)
    return None


# =====================
# ルート定義
# =====================
@app.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_RATE_LIMIT, methods=["POST"])
def login():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT username, password, role, name "
                "FROM users WHERE username=? AND is_active=1",
                (u,),
            ).fetchone()
        if row and check_password_hash(row[1], p):
            # P: 旧セッションを必ず破棄してから新規セッションを設定
            # V11: session には username のみ保持（role/name は load_current_user が DB から再取得）
            session.clear()
            # V28: PERMANENT_SESSION_LIFETIME（無操作タイムアウト）を効かせる。
            # session.clear() が permanent を False に戻すため、必ずこの後に設定する。
            session.permanent = True
            session["username"] = row[0]
            # V28: g.user はまだ未設定（次リクエストで確定）のため actor を明示
            log_event("login_success", actor=row[0], actor_name=row[3])
            return redirect(url_for("menu"))
        # V27: 該当ユーザーが居ない場合もダミー検証で応答時間を揃える（ID 列挙対策）
        if not row:
            check_password_hash(_DUMMY_PW_HASH, p)
        # V28: 失敗は試行 ID を actor として記録（パスワードは記録しない）
        log_event("login_fail", actor=(u or "anonymous"))
        return render_template("login.html", error="IDまたはパスワードが正しくありません")
    return render_template("login.html")


@app.route("/menu")
def menu():
    if not require_login():
        return redirect(url_for("login"))
    links = get_month_links()
    with closing(get_db()) as conn:
        # V28: 未提出判定も username を権威キーに（表示名変更後もズレない）
        exists = conn.execute(
            "SELECT 1 FROM shifts WHERE year=? AND month=? AND username=?",
            (links["next_y"], links["next_m"], g.user.username),
        ).fetchone()
    return render_template("menu.html", unsubmitted=not exists, next_m=links["next_m"])


def handle_input(template, target_username, target_name, confirmed=False):
    """カレンダー入力の共通処理（V28 で username 基準に一般化）。

    confirmed=False: 希望(shifts) を本人が提出。備考あり。
    confirmed=True:  確定(confirmed_shifts) を管理者が編集。備考なし。GET 時は当人の
                     希望を request_hint として下敷き表示する。
    DELETE/INSERT は **username** を権威キーにする（表示名の改ざん・rename に影響されない）。
    table 名は user 入力ではなくサーバ制御の分岐で切替（動的 SQL を作らない方針を維持）。
    """
    now = datetime.now()
    year, month = safe_ym(now.year, now.month)
    cal = calendar.monthcalendar(year, month)

    if request.method == "POST":
        ok_count = 0
        with closing(get_db()) as conn, conn:
            if confirmed:
                conn.execute(
                    "DELETE FROM confirmed_shifts WHERE year=? AND month=? AND username=?",
                    (year, month, target_username),
                )
            else:
                conn.execute(
                    "DELETE FROM shifts WHERE year=? AND month=? AND username=?",
                    (year, month, target_username),
                )
            for week in cal:
                for i, day in enumerate(week):
                    if day != 0 and i in [0, 1, 4]:  # 日・月・木
                        status = request.form.get(f"day_{day}", "×")
                        if status not in ("〇", "×"):
                            status = "×"
                        if status == "〇":
                            ok_count += 1
                        if confirmed:
                            conn.execute(
                                "INSERT INTO confirmed_shifts (year, month, day, username, status) "
                                "VALUES (?,?,?,?,?)",
                                (year, month, day, target_username, status),
                            )
                        else:
                            remark = (request.form.get(f"remark_{day}", "") or "")[:REMARK_MAX_LEN]
                            conn.execute(
                                "INSERT INTO shifts (year, month, day, username, name, status, remarks) "
                                "VALUES (?,?,?,?,?,?,?)",
                                (year, month, day, target_username, target_name, status, remark),
                            )
            # V28: 監査ログ。備考(remark)本文は記録せず、年月と〇件数のメタのみ。
            # detail には安定ID(username)を必ず含める（表示名変更後も「誰の分か」を追跡可能に）。
            # target は年月のまま（/submissions の最終提出時刻クエリが target=YYYY-MM を使うため）。
            log_action(
                conn, "confirm_save" if confirmed else "request_submit",
                target=f"{year}-{month:02d}",
                detail={"username": target_username, "name": target_name, "ok": ok_count},
            )
        if confirmed:
            flash("確定シフトを保存しました")
            return redirect(url_for("confirm_user", username=target_username,
                                    year=year, month=month))
        if template == "index.html":
            return redirect(url_for("index", year=year, month=month, submitted="true"))
        return redirect(url_for("worker", name=target_name, year=year, month=month, submitted="true"))

    with closing(get_db()) as conn:
        if confirmed:
            existing = {
                row[0]: {"status": row[1], "remark": ""}
                for row in conn.execute(
                    "SELECT day, status FROM confirmed_shifts WHERE year=? AND month=? AND username=?",
                    (year, month, target_username),
                ).fetchall()
            }
            # 下敷きヒント: 当人の希望（〇/×）
            request_hint = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT day, status FROM shifts WHERE year=? AND month=? AND username=?",
                    (year, month, target_username),
                ).fetchall()
            }
        else:
            existing = {
                row[0]: {"status": row[1], "remark": row[2]}
                for row in conn.execute(
                    "SELECT day, status, remarks FROM shifts WHERE year=? AND month=? AND username=?",
                    (year, month, target_username),
                ).fetchall()
            }
            request_hint = {}
    return render_template(
        template, name=target_name, year=year, month=month, cal=cal, shifts=existing,
        request_hint=request_hint, target_username=target_username, **get_month_links()
    )


@app.route("/", methods=["GET", "POST"])
def index():
    guard = deny_if_not_admin()
    if guard:
        return guard
    return handle_input("index.html", g.user.username, g.user.name)


@app.route("/worker/<name>", methods=["GET", "POST"])
def worker(name):
    if not require_login():
        return redirect(url_for("login"))
    # V8: 他人のシフト入力画面を叩いたときはログイン画面ではなくメニューへ
    # （「ログアウトされた？」と混乱するのを防ぐ）
    if g.user.name != name:
        flash("自分のシフト入力画面以外にはアクセスできません")
        return redirect(url_for("menu"))
    # V28: 書き込みキーは認証済みの username（path の name は本人確認のみに使用）
    return handle_input("worker.html", g.user.username, g.user.name)


@app.route("/admin")
def admin():
    # N: /admin は管理者専用（V29: 共通ガードに統一＋authz_fail 記録）
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = datetime.now()
    year, month = safe_ym(now.year, now.month)
    with closing(get_db()) as conn:
        # V28: JOIN を username 基準に（rename 取りこぼし解消）。表示名・色は users 側の最新を使う
        rows = conn.execute(
            "SELECT s.day, u.name, s.status, u.color, s.remarks "
            "FROM shifts s INNER JOIN users u ON s.username = u.username "
            "WHERE s.year=? AND s.month=?",
            (year, month),
        ).fetchall()
    return render_template(
        "admin.html",
        year=year, month=month,
        cal=calendar.monthcalendar(year, month),
        rows=rows,
        **get_month_links(),
    )


@app.route("/manage_users", methods=["GET", "POST"])
def manage_users():
    guard = deny_if_not_admin()
    if guard:
        return guard
    with closing(get_db()) as conn:
        if request.method == "POST":
            with conn:
                action = request.form.get("action")
                # V20: 編集モードでは original_username を権威とし、フォームの username 入力は無視
                #   1) DB 検索キーが書き換わらないことを保証
                #   2) 「太郎を修正したつもりが新規ユーザー作成」事故を防止
                mode = (request.form.get("mode") or "create").strip()
                original_username = (request.form.get("original_username") or "").strip()
                if action == "add" and mode == "edit":
                    u = original_username
                else:
                    u = (request.form.get("username") or "").strip()
                if not USERNAME_RE.match(u):
                    flash("ユーザーIDの形式が不正です（半角英数記号 1〜32文字）")
                elif action == "add":
                    # F: REPLACE INTO を廃止。既存なら UPDATE、無ければ INSERT。
                    p = request.form.get("password") or ""
                    n = (request.form.get("name") or "").strip()
                    r = request.form.get("role")
                    col = request.form.get("color") or "#e8f5e9"
                    existing = conn.execute(
                        "SELECT name, role FROM users WHERE username=?", (u,)
                    ).fetchone()
                    # Codex(後追加)#2: 表示名の重複検査（同 username なら自分自身なので除外）
                    dup = conn.execute(
                        "SELECT username FROM users WHERE name=? AND username != ?",
                        (n, u),
                    ).fetchone()
                    # Codex#1: すべての検証を先に通し、検証通過後にだけ DB を更新する
                    # （検証失敗時に shifts.name だけ先に変わって users と不整合になる事故を防ぐ）
                    if mode == "edit" and not existing:
                        # V20: 編集対象が消えている / ID 改ざんを検知
                        flash("編集対象のユーザーが見つかりません。ID 変更は禁止です（停止 → 削除 → 新規登録の手順で行ってください）")
                    elif mode == "create" and existing:
                        # V20: 重複登録を明示的に拒否（修正したいなら一覧の「修正」を使う）
                        flash(f"そのID（{u}）は既に登録されています。修正する場合は一覧の「修正」ボタンから操作してください")
                    elif r not in ("admin", "worker"):
                        flash("権限の値が不正です")
                    elif not HEX_COLOR_RE.match(col):
                        flash("色コードの形式が不正です（#RRGGBB）")
                    elif not n or len(n) > 32:
                        flash("お名前は1〜32文字で入力してください")
                    elif NAME_FORBIDDEN_RE.search(n):
                        # Codex(後追加)#3: 表示名は URL パスに入るため / 等を禁止
                        flash("お名前に使えない文字（/ \\ ? # & < > 改行 等）が含まれています")
                    elif dup:
                        flash(f"同じ表示名のユーザー（ID: {dup[0]}）が既に存在します")
                    elif existing and p and not is_valid_password(p):
                        flash("パスワードは8文字以上で入力してください")
                    elif not existing and not is_valid_password(p):
                        flash("パスワードは8文字以上で入力してください")
                    elif existing and existing[1] != r and u == g.user.username:
                        # Codex(後追加)#1: 自分自身の権限変更を禁止（自己降格による締め出し防止）
                        flash("自分自身の権限は変更できません")
                    elif (
                        existing
                        and existing[1] == "admin"
                        and r == "worker"
                        and conn.execute(
                            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
                        ).fetchone()[0]
                        <= 1
                    ):
                        # Codex(後追加)#1: 最後の有効な管理者は降格できない
                        flash("有効な管理者が最低1人残るよう、最後の管理者を降格することはできません")
                    else:
                        if existing:
                            # 表示名変更時はシフト名も連動（J の根本対応はフェーズ3）
                            if existing[0] != n:
                                conn.execute(
                                    "UPDATE shifts SET name=? WHERE name=?",
                                    (n, existing[0]),
                                )
                            if p:
                                # V23: 管理者が新しいパスワードを設定した場合は
                                # 本人の初回ログイン時に強制変更を促す
                                conn.execute(
                                    "UPDATE users SET password=?, role=?, name=?, color=?, "
                                    "must_change_password=1 WHERE username=?",
                                    (generate_password_hash(p), r, n, col, u),
                                )
                                log_action(conn, "user_edit", target=u, detail={"name": n, "role": r})
                                # V28: 管理者による他人のパスワード設定を専用イベントで記録（再発行運用の証跡）
                                log_action(conn, "admin_password_set", target=u)
                                flash("ユーザー情報を保存しました（本人は次回ログイン時にパスワード変更を求められます）")
                            else:
                                # A: 編集時にパスワード空欄ならパスワードは据え置き
                                conn.execute(
                                    "UPDATE users SET role=?, name=?, color=? WHERE username=?",
                                    (r, n, col, u),
                                )
                                log_action(conn, "user_edit", target=u, detail={"name": n, "role": r})
                                flash("ユーザー情報を保存しました（パスワードは変更なし）")
                        else:
                            # V23: 新規ユーザーは初回ログイン時にパスワード変更必須
                            conn.execute(
                                "INSERT INTO users "
                                "(username, password, role, name, is_active, color, must_change_password) "
                                "VALUES (?, ?, ?, ?, 1, ?, 1)",
                                (u, generate_password_hash(p), r, n, col),
                            )
                            log_action(conn, "user_create", target=u, detail={"name": n, "role": r})
                            flash("ユーザーを登録しました（本人は初回ログイン時にパスワード変更を求められます）")
                elif action == "toggle":
                    try:
                        s = int(request.form.get("current_status", ""))
                    except ValueError:
                        s = -1
                    # Codex(後追加)#1: 自分自身の停止禁止 + 最後の有効 admin の停止禁止
                    if u == g.user.username:
                        flash("自分自身を停止することはできません")
                    elif u == "admin":
                        # 既存の固定保護（初期 admin 行）を維持
                        pass
                    elif s in (0, 1):
                        allow = True
                        if s == 1:  # 1 → 0（停止に向かう）
                            target = conn.execute(
                                "SELECT role FROM users WHERE username=?", (u,)
                            ).fetchone()
                            if target and target[0] == "admin":
                                admin_count = conn.execute(
                                    "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
                                ).fetchone()[0]
                                if admin_count <= 1:
                                    flash("最後の有効な管理者を停止することはできません")
                                    allow = False
                        if allow:
                            new_active = 0 if s == 1 else 1
                            conn.execute(
                                "UPDATE users SET is_active=? WHERE username=?",
                                (new_active, u),
                            )
                            log_action(conn, "user_toggle", target=u, detail={"is_active": new_active})
                elif action == "delete":
                    # V19: 試用初期は UI から削除ボタンを撤去（manage_users.html）。
                    # 万一直接 POST が来ても、停止運用に寄せるため一律で拒否する。
                    # 物理削除が必要なら、バックアップ後に管理 CLI（sqlite3）で行う運用。
                    flash("削除は管理操作で行ってください。停止で十分なケースが大半です。")
        # A: パスワード列は読み出さない（HTMLに渡さない）
        users = conn.execute(
            "SELECT username, role, name, is_active, color FROM users"
        ).fetchall()
    return render_template("manage_users.html", users=users)


@app.route("/logs")
def logs():
    # V28: 操作ログの閲覧（管理者専用）。V29: 共通ガードに統一。
    guard = deny_if_not_admin()
    if guard:
        return guard
    page = request.args.get("page", 1, type=int)
    if not isinstance(page, int) or page < 1:
        page = 1
    per = 100
    offset = (page - 1) * per
    with closing(get_db()) as conn:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        rows = conn.execute(
            "SELECT ts, actor, actor_name, action, target, detail, ip "
            "FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (per, offset),
        ).fetchall()
    return render_template(
        "logs.html", rows=rows, page=page, total=total,
        has_next=(offset + per < total),
    )


@app.route("/submissions")
def submissions():
    # V28: 提出状況の一覧（管理者専用）。shifts から導出し、最終提出時刻は audit_log から取得。
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = datetime.now()
    year, month = safe_ym(now.year, now.month)
    with closing(get_db()) as conn:
        users = conn.execute(
            "SELECT username, name, role FROM users WHERE is_active=1 ORDER BY name"
        ).fetchall()
        ok_counts = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT username, SUM(CASE WHEN status='〇' THEN 1 ELSE 0 END) "
                "FROM shifts WHERE year=? AND month=? GROUP BY username",
                (year, month),
            ).fetchall()
        }
        submitted = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT username FROM shifts WHERE year=? AND month=?",
                (year, month),
            ).fetchall()
        }
        last_at = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT actor, MAX(ts) FROM audit_log "
                "WHERE action='request_submit' AND target=? GROUP BY actor",
                (f"{year}-{month:02d}",),
            ).fetchall()
        }
    items = [
        {
            "username": u[0], "name": u[1], "role": u[2],
            "submitted": u[0] in submitted,
            "ok": ok_counts.get(u[0], 0) or 0,
            "last": last_at.get(u[0], ""),
        }
        for u in users
    ]
    pending = sum(1 for it in items if not it["submitted"])
    return render_template(
        "submissions.html", items=items, pending=pending,
        year=year, month=month, **get_month_links()
    )


@app.route("/confirm")
def confirm():
    # V28: 確定シフトの作成/編集（管理者専用）。職員を選んで個別に編集する一覧。
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = datetime.now()
    year, month = safe_ym(now.year, now.month)
    with closing(get_db()) as conn:
        users = conn.execute(
            "SELECT username, name, color FROM users WHERE is_active=1 ORDER BY name"
        ).fetchall()
        confirmed_counts = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT username, SUM(CASE WHEN status='〇' THEN 1 ELSE 0 END) "
                "FROM confirmed_shifts WHERE year=? AND month=? GROUP BY username",
                (year, month),
            ).fetchall()
        }
    items = [
        {"username": u[0], "name": u[1], "color": u[2],
         "confirmed_ok": confirmed_counts.get(u[0], 0) or 0}
        for u in users
    ]
    return render_template(
        "confirm_list.html", items=items, year=year, month=month, **get_month_links()
    )


@app.route("/confirm/<username>", methods=["GET", "POST"])
def confirm_user(username):
    # V28: 指定職員の確定シフトを編集（管理者専用）。username は ? バインドで安全に照合。
    guard = deny_if_not_admin()
    if guard:
        return guard
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT username, name FROM users WHERE username=? AND is_active=1",
            (username,),
        ).fetchone()
    if not row:
        flash("対象の職員が見つかりません（停止中の可能性があります）")
        return redirect(url_for("confirm"))
    return handle_input("confirm_edit.html", row[0], row[1], confirmed=True)


@app.route("/confirmed")
def confirmed():
    # V28: 確定シフトのチーム全体表示（ログイン必須・読み取り専用）。備考は出さない。
    if not require_login():
        return redirect(url_for("login"))
    now = datetime.now()
    year, month = safe_ym(now.year, now.month)
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT s.day, u.name, u.color "
            "FROM confirmed_shifts s INNER JOIN users u ON s.username = u.username "
            "WHERE s.year=? AND s.month=? AND s.status='〇'",
            (year, month),
        ).fetchall()
    return render_template(
        "confirmed.html", year=year, month=month,
        cal=calendar.monthcalendar(year, month), rows=rows, **get_month_links()
    )


@app.route("/change_password", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def change_password():
    # V1: ログイン必須化（未ログインの username 当て攻撃面を撤去）。
    # V23: must_change_password=1 の本人もこの画面に強制誘導される。
    if not require_login():
        return redirect(url_for("login"))
    u = g.user.username
    if request.method == "POST":
        p_curr = request.form.get("password_current") or ""
        p_new = request.form.get("password_new") or ""
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT password FROM users WHERE username=? AND is_active=1", (u,)
            ).fetchone()
        if not row or not check_password_hash(row[0], p_curr) or not is_valid_password(p_new):
            return render_template(
                "change_password.html",
                error="現在のパスワードが間違っているか、新しいパスワードが不正です（8文字以上）",
            )
        with closing(get_db()) as conn, conn:
            # V23: 変更成功で must_change_password=0 に戻す
            conn.execute(
                "UPDATE users SET password=?, must_change_password=0 WHERE username=?",
                (generate_password_hash(p_new), u),
            )
            # V28: 監査ログ（新旧パスワードは記録しない）
            log_action(conn, "password_change")
        session.clear()
        flash("パスワードを変更しました。再度ログインしてください。")
        return redirect(url_for("login"))
    return render_template("change_password.html")


@app.route("/help")
def help_page():
    # ログイン済みなら役割別、未ログインなら基本のみ表示
    return render_template("help.html")


@app.route("/logout")
def logout():
    # V28: session.clear() の前に記録（actor を g.user から取得できるうちに）
    if getattr(g, "user", None):
        log_event("logout")
    session.clear()
    return redirect(url_for("login"))


@app.route("/healthz")
def healthz():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    # G: 本番では gunicorn 起動を強制し debug 実行を禁止
    if IS_PROD:
        raise RuntimeError("本番では gunicorn 経由で起動してください（debug 実行は禁止）")
    app.run(debug=False)
