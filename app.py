import re
import json
import secrets
import calendar
import ipaddress
import unicodedata
from contextlib import closing
from datetime import datetime, timedelta
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

from security_utils import (
    is_valid_password,
    normalize_password,
    password_error,
)
from settings import load_settings
from storage import DatabaseManager
from time_utils import format_jst, now_jst, now_utc


def create_app():
    application = Flask(__name__)
    settings = load_settings(application.instance_path)
    application.extensions["shift_settings"] = settings
    application.secret_key = settings.secret_key
    application.config.update(
        SESSION_COOKIE_SECURE=settings.is_prod,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME=("__Host-sfid" if settings.is_prod else "sfid"),
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=settings.session_idle_minutes),
        MAX_CONTENT_LENGTH=256 * 1024,
    )
    # Host ヘッダ検証（設定時のみ）。Flask が Host/X-Forwarded-Host を照合し不一致は 400。
    if settings.trusted_hosts:
        application.config["TRUSTED_HOSTS"] = list(settings.trusted_hosts)
    if settings.trusted_proxy_hops:
        application.wsgi_app = ProxyFix(
            application.wsgi_app,
            x_for=settings.trusted_proxy_hops,
            x_proto=settings.trusted_proxy_hops,
            x_host=settings.trusted_proxy_hops,
        )
    return application


app = create_app()
app.jinja_env.filters["jst"] = format_jst
SETTINGS = app.extensions["shift_settings"]
APP_ENV = SETTINGS.app_env
IS_PROD = SETTINGS.is_prod
SECRET_KEY = SETTINGS.secret_key
TRUSTED_PROXY_HOPS = SETTINGS.trusted_proxy_hops
SESSION_IDLE_MINUTES = SETTINGS.session_idle_minutes
SESSION_ABSOLUTE_HOURS = SETTINGS.session_absolute_hours
TRUST_CF_CONNECTING_IP = SETTINGS.trust_cf_connecting_ip
LOGIN_RATE_LIMIT = SETTINGS.login_rate_limit
DB_PATH = SETTINGS.db_path
BACKUP_KEEP = SETTINGS.daily_backup_keep
BACKUP_ON_STARTUP = SETTINGS.backup_enabled
AUDIT_RETENTION = SETTINGS.audit_retention

csrf = CSRFProtect(app)

def client_ip():
    """レート制限キー・監査ログ用のクライアント IP を決める。

    TRUST_CF_CONNECTING_IP=1 のときだけ CF-Connecting-IP を優先する。これは
    「全インバウンドが Cloudflare/Render エッジを経由し、オリジン（Render の web
    サービス）へエッジを迂回して直接到達する経路が無い」という構成が前提（Cloudflare
    公式: CF-Connecting-IP はエッジ経由が 100% 保証される場合のみ信頼してよい）。
    ここでの ipaddress 検証は「IP 形式か」だけを見るもので、妥当な形式の偽装 IP は
    防げない＝なりすまし対策ではない。前提が崩れる構成（Render 外への移設、オリジン
    直公開など）では TRUST_CF_CONNECTING_IP=0 に戻すか、送信元を Cloudflare の IP
    レンジに限定すること。形式不正・不在時は ProxyFix 経由の remote_addr へフォールバック。
    デプロイ後は /logs の IP が実クライアント IP かを確認して 0/1 を確定する。
    """
    if TRUST_CF_CONNECTING_IP:
        cf = request.headers.get("CF-Connecting-IP")
        if cf:
            candidate = cf.split(",")[0].strip()
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass
    return get_remote_address()


limiter = Limiter(
    client_ip,
    app=app,
    default_limits=[],
    storage_uri=SETTINGS.rate_limit_storage_uri,
)

db_manager = DatabaseManager(
    DB_PATH,
    is_prod=IS_PROD,
    backup_enabled=BACKUP_ON_STARTUP,
    daily_keep=BACKUP_KEEP,
    monthly_keep=SETTINGS.monthly_backup_keep,
)

# カレンダーを日曜日始まりに固定
calendar.setfirstweekday(calendar.SUNDAY)


def get_db():
    db_manager.ensure_ready()
    return db_manager.connect()


def init_db():
    db_manager.reconcile_schema()


def backup_db(kind="manual"):
    db_manager.ensure_ready()
    return db_manager.backup(kind)


# =====================
# 入力検証ヘルパー
# =====================
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,32}$")
# 旧URL互換とログの可読性を保つため、予約文字と制御文字を拒否する。
NAME_FORBIDDEN_RE = re.compile(r"[/\\?#&<>\r\n\t\x00]")
REMARK_MAX_LEN = 500
# 備考は自由入力。表示崩れ・ログ汚染を防ぐため保存前に正規化する（改行・タブは残す）。
_REMARK_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_remark(text):
    """備考の保存前正規化: NFC・制御文字除去・改行統一/連続上限・長さ上限。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _REMARK_CONTROL_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:REMARK_MAX_LEN]


def get_month_links():
    now = now_jst()
    next_date = now.replace(day=1) + timedelta(days=32)
    return {
        "now_y": now.year, "now_m": now.month,
        "next_y": next_date.year, "next_m": next_date.month,
    }


def coerce_year_month(source, default_y, default_m):
    """source(request.args または request.values)から year/month を範囲検証して返す。

    safe_ym / resolve_ym の共通の低レベル処理。両者は「どの source を読むか」だけ違うため
    検証ロジックをここに一本化する（統合はせず、用途別の薄いラッパとして役割を残す）。
    """
    y = source.get("year", default_y, type=int)
    m = source.get("month", default_m, type=int)
    if not isinstance(m, int) or not (1 <= m <= 12):
        m = default_m
    if not isinstance(y, int) or not (2000 <= y <= 2100):
        y = default_y
    return y, m


def safe_ym(default_y, default_m):
    # O: year/month の範囲検証（GET 表示用。クエリのみ参照）
    return coerce_year_month(request.args, default_y, default_m)


def resolve_ym(default_y, default_m):
    """保存先となる年月を一意に決める（GET=クエリ / POST=隠しフィールド+クエリ）。
    呼び出し側はこの 1 回の結果をロック判定と保存の両方に使い、月のズレを防ぐ。
    request.values は args+form を統合し、POST の保存対象月を確実に拾う。"""
    return coerce_year_month(request.values, default_y, default_m)


# =====================
# 締め切り（年月ごとに管理者が設定。この日からスタッフは変更不可）
# =====================
def get_deadline(conn, year, month):
    row = conn.execute(
        "SELECT deadline FROM deadlines WHERE year=? AND month=?",
        (year, month),
    ).fetchone()
    return row[0] if row and row[0] else None


def set_deadline(conn, year, month, date_str):
    if date_str:
        conn.execute(
            "INSERT INTO deadlines (year, month, deadline) VALUES (?,?,?) "
            "ON CONFLICT(year, month) DO UPDATE SET deadline=excluded.deadline",
            (year, month, date_str),
        )
    else:
        conn.execute(
            "DELETE FROM deadlines WHERE year=? AND month=?", (year, month)
        )


def parse_deadline(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def deadline_label(date_str):
    d = parse_deadline(date_str)
    return f"{d.month}月{d.day}日" if d else ""


def is_locked_for_staff(date_str):
    """締め切り日当日0:00(JST)以降はスタッフ編集をロックする。"""
    d = parse_deadline(date_str)
    return d is not None and now_jst().date() >= d


# =====================
# Q: 各リクエストで DB からユーザー状態を再取得
# =====================
@app.before_request
def load_current_user():
    g.csp_nonce = secrets.token_urlsafe(16)
    g.user = None
    if request.endpoint in {"static", "healthz", "readyz"}:
        return
    db_manager.ensure_ready()
    u = session.get("username")
    if not u:
        return
    authenticated_at = session.get("authenticated_at")
    if authenticated_at:
        try:
            login_time = datetime.fromisoformat(authenticated_at)
        except (TypeError, ValueError):
            login_time = None
        if login_time is None or login_time.tzinfo is None:
            session.clear()
            flash("安全のためログアウトしました。もう一度ログインしてください。")
            return
        if now_utc() - login_time >= timedelta(hours=SESSION_ABSOLUTE_HOURS):
            session.clear()
            flash("安全のためログアウトしました。もう一度ログインしてください。")
            return
    else:
        # 旧セッションは更新後の最初のアクセス時点から総有効期限を開始する。
        session["authenticated_at"] = now_utc().isoformat(timespec="seconds")
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT username, role, name, is_active "
            "FROM users WHERE username=?",
            (u,),
        ).fetchone()
    if not row or row[3] == 0:
        # 削除または停止済み → 旧セッションを破棄
        session.clear()
        return
    g.user = SimpleNamespace(username=row[0], role=row[1], name=row[2])


@app.context_processor
def inject_current_user():
    # テンプレも session['role'] ではなく current_user.role を使うように統一
    # 全テンプレの <script nonce="..."> 用に csp_nonce も渡す
    return {
        "current_user": getattr(g, "user", None),
        "csp_nonce": getattr(g, "csp_nonce", ""),
    }


# CSRF トークン期限切れ時の親切な UX 救済
# 既定の 400 ページに着地すると「シフトを出したつもりが消えた」事故になるため、
# セッションを破棄しログイン画面に flash 付きで送る。
# 重要: flash() は内部で session を使うため session.clear() → flash() → redirect() の順。
@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    # セッション破棄の前に記録（actor は g.user か anonymous）
    safe_log_event("csrf_error", target=(request.path or "")[:128])
    session.clear()
    flash("セッションが切れました。もう一度ログインしてください。")
    return redirect(url_for("login"))


# 外部読み込み、inline script/style、フレーム埋め込み、外部フォーム送信を遮断する。
def _build_csp(nonce):
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self'; "
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
    # 静的以外の全動的応答を端末・中間キャッシュに残さない（共有/個人端末の戻るボタン
    # 対策、login の CSRF トークン鮮度、CVE-2026-27205 = session アクセス時の Vary: Cookie 欠落緩和）。
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    # O-1: 日次バックアップを POST 成功時だけでなく、通常ページの成功 GET でも起動する。
    # 24h スロットル（_scheduled_backup_due）＋ロックで多重・長時間化を防ぐため、誰かが
    # 画面を開けば「書き込みの無い期間」でもその日のバックアップが取得される。
    if (
        BACKUP_ON_STARTUP
        and resp.status_code < 400
        and request.endpoint not in {"static", "healthz", "readyz"}
    ):
        try:
            db_manager.scheduled_backup()
        except Exception as exc:
            print(f"[backup] 自動バックアップ失敗: {exc}")
    return resp


# カスタムエラーページ。スタックトレースの露出を防ぎ、職員が迷子にならないように
# メニュー / ログインへの導線を提示する。
@app.errorhandler(403)
def handle_403(e):
    return render_template(
        "error.html",
        code=403,
        title="この画面は開けません",
        message="管理者だけが使う画面です。メニューから操作をやり直してください。",
    ), 403


@app.errorhandler(404)
def handle_404(e):
    return render_template(
        "error.html",
        code=404,
        title="ページが見つかりません",
        message="URLが変更された可能性があります。メニューから操作をやり直してください。",
    ), 404


@app.errorhandler(500)
def handle_500(e):
    return render_template(
        "error.html",
        code=500,
        title="一時的なエラーが発生しました",
        message="少し待ってからやり直してください。繰り返す場合は管理者へ連絡してください。",
    ), 500


@app.errorhandler(413)
def handle_413(e):
    return render_template(
        "error.html",
        code=413,
        title="入力内容が大きすぎます",
        message="備考を短くして、もう一度保存してください。",
    ), 413


def require_login():
    return g.user is not None


def require_admin():
    return g.user is not None and g.user.role == "admin"


# ログイン失敗時、ユーザーの存在有無で応答時間が変わると ID 列挙の手がかりになる。
# 該当ユーザーが無い場合もこのダミーハッシュで検証を回し、処理時間を平準化する。
_DUMMY_PW_HASH = generate_password_hash("not-a-real-password")


# =====================
# 監査ログ（操作ログ）
# =====================
_AUDIT_DETAIL_MAX = 500


def _serialize_detail(detail):
    """監査ログ detail を文字列化し、長さ上限で切り詰める。

    禁止（呼び出し側の責務）: パスワード/ハッシュ/セッション値/備考(remark)本文/CSRF
    トークンは detail に渡さない。dict は JSON 文字列化する。検証は test_audit で固定。
    """
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    return detail[:_AUDIT_DETAIL_MAX]


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
    try:
        ip = client_ip() or ""
    except Exception:
        ip = ""
    conn.execute(
        "INSERT INTO audit_log (ts, actor, actor_name, action, target, detail, ip) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            now_utc().isoformat(timespec="seconds"),
            (actor or "")[:64],
            (actor_name or "")[:64],
            (action or "")[:32],
            (target or "")[:128],
            _serialize_detail(detail),
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


def safe_log_event(action, target="", detail="", actor=None, actor_name=None):
    """監査DBの障害で認証・認可の本処理を失敗させない。"""
    try:
        log_event(action, target, detail, actor, actor_name)
    except Exception:
        app.logger.exception("監査ログの保存に失敗しました: %s", action)


# 管理者専用ルートの共通ガード（認可を一貫させる）。
#   未ログイン      → login へリダイレクト（呼び出し側で return する）
#   ログイン済み非管理者 → authz_fail を監査記録して 403（abort で送出）
#   管理者          → None（呼び出し側は処理続行）
def deny_if_not_admin():
    if not require_login():
        return redirect(url_for("login"))
    if not require_admin():
        safe_log_event("authz_fail", target=(request.path or "")[:128])
        abort(403)
    return None


# =====================
# ルート定義（初心者向けの地図。Blueprint 分割はせず単一ファイルで追えるようにする）
#   認証:   /login  /logout  /change_password
#   入力:   /worker（職員本人）  /（管理者本人）
#   集計:   /menu  /admin（みんなの希望）  /submissions（提出状況・締め切り）
#   管理:   /staff/<u>（代理編集）  /manage_users  /logs  /deadline  /backup_check
#   監視:   /healthz  /readyz   その他: /help
#   互換:   /confirm  /confirmed（旧確定シフト。リダイレクトのみ・撤去予定）
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
        normalized_password = normalize_password(p)
        valid_password = bool(
            row
            and (
                check_password_hash(row[1], p)
                or (
                    normalized_password != p
                    and check_password_hash(row[1], normalized_password)
                )
            )
        )
        if valid_password:
            # P: 旧セッションを必ず破棄してから新規セッションを設定
            # session には username のみ保持（role/name は load_current_user が DB から再取得）
            session.clear()
            # PERMANENT_SESSION_LIFETIME（無操作タイムアウト）を効かせる。
            # session.clear() が permanent を False に戻すため、必ずこの後に設定する。
            session.permanent = True
            session["username"] = row[0]
            session["authenticated_at"] = now_utc().isoformat(timespec="seconds")
            # g.user はまだ未設定（次リクエストで確定）のため actor を明示
            safe_log_event("login_success", actor=row[0], actor_name=row[3])
            return redirect(url_for("menu"))
        # 該当ユーザーが居ない場合もダミー検証で応答時間を揃える（ID 列挙対策）
        if not row:
            check_password_hash(_DUMMY_PW_HASH, p)
        # 失敗は試行 ID を actor として記録（パスワードは記録しない）
        safe_log_event("login_fail", actor=(u or "anonymous"))
        return render_template("login.html", error="IDまたはパスワードが正しくありません")
    return render_template("login.html")


def _is_external_check_overdue(value, days=31):
    """月次の外部保存確認が一定日数(既定31日)以上記録されていなければ True。"""
    if not value:
        return True
    try:
        last = datetime.fromisoformat(value)
        return now_utc() - last >= timedelta(days=days)
    except (TypeError, ValueError):
        return True


@app.route("/menu")
def menu():
    if not require_login():
        return redirect(url_for("login"))
    links = get_month_links()
    # M-1/U-3: 当月と翌月の両方で未提出を判定し、未提出かつ入力可能な月だけを促す。
    # 「未提出と言われた月」と「入力ボタンが開く月」を必ず一致させ、当月の出し忘れも拾う。
    candidate_months = [
        (links["now_y"], links["now_m"]),
        (links["next_y"], links["next_m"]),
    ]
    unsubmitted = []
    with closing(get_db()) as conn:
        for yy, mm in candidate_months:
            # 未提出判定も username を権威キーに（表示名変更後もズレない）
            submitted = conn.execute(
                "SELECT 1 FROM shifts WHERE year=? AND month=? AND username=?",
                (yy, mm, g.user.username),
            ).fetchone()
            # 締め切り後は職員が出せないので促さない（管理者はロック対象外）。
            locked = is_locked_for_staff(get_deadline(conn, yy, mm))
            if not submitted and (g.user.role == "admin" or not locked):
                unsubmitted.append((yy, mm))
    # 入力ボタンの着地月: 未提出のうち最も早い月（無ければ翌月）。
    worker_year, worker_month = unsubmitted[0] if unsubmitted else (links["next_y"], links["next_m"])
    backup_state = db_manager.status()
    external_checked = backup_state.get("last_external_backup_checked", "")
    return render_template(
        "menu.html",
        unsubmitted_months=[mm for _, mm in unsubmitted],
        worker_year=worker_year,
        worker_month=worker_month,
        backup_error=backup_state.get("last_backup_error", ""),
        backup_success=backup_state.get("last_backup_success", ""),
        external_checked=external_checked,
        external_overdue=_is_external_check_overdue(external_checked),
        disk_low=backup_state.get("disk_free_ratio", 1) < 0.1,
    )


def handle_input(
    template,
    target_username,
    target_name,
    *,
    year,
    month,
    redirect_endpoint,
    redirect_kwargs=None,
    read_only=False,
    editor_is_admin=False,
    deadline=None,
    log_action_name="request_submit",
):
    """シフト希望（shifts）の入力・編集の共通処理。

    year/month は呼び出し側が resolve_ym で確定して渡す（ロック判定と保存先を一致させる）。
    read_only=True のときは保存せず読み取り専用で描画する。
    """
    cal = calendar.monthcalendar(year, month)
    redirect_kwargs = redirect_kwargs or {}

    if request.method == "POST" and not read_only:
        ok_count = 0
        with closing(get_db()) as conn, conn:
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
                        remark = normalize_remark(request.form.get(f"remark_{day}", ""))
                        conn.execute(
                            "INSERT INTO shifts (year, month, day, username, name, status, remarks) "
                            "VALUES (?,?,?,?,?,?,?)",
                            (year, month, day, target_username, target_name, status, remark),
                        )
            # 監査ログ。備考(remark)本文は記録せず、年月・対象者・〇件数のメタのみ。
            # target は "YYYY-MM:対象username" 形式（代理編集も含め誰の分かを正確に集計できる）。
            actor = g.user.username if getattr(g, "user", None) else target_username
            log_action(
                conn, log_action_name,
                target=f"{year}-{month:02d}:{target_username}",
                detail={"name": target_name, "ok": ok_count, "by": actor},
            )
        return redirect(
            url_for(redirect_endpoint, **redirect_kwargs,
                    year=year, month=month, submitted="true")
        )

    with closing(get_db()) as conn:
        existing = {
            row[0]: {"status": row[1], "remark": row[2]}
            for row in conn.execute(
                "SELECT day, status, remarks FROM shifts WHERE year=? AND month=? AND username=?",
                (year, month, target_username),
            ).fetchall()
        }
    links = get_month_links()
    nav_now_url = url_for(redirect_endpoint, **redirect_kwargs,
                          year=links["now_y"], month=links["now_m"])
    nav_next_url = url_for(redirect_endpoint, **redirect_kwargs,
                           year=links["next_y"], month=links["next_m"])
    return render_template(
        template, name=target_name, year=year, month=month, cal=cal, shifts=existing,
        read_only=read_only, editor_is_admin=editor_is_admin,
        deadline_label=deadline_label(deadline),
        target_username=target_username,
        nav_now_url=nav_now_url, nav_next_url=nav_next_url,
        weekday_names=("日", "月", "火", "水", "木", "金", "土"),
        **links,
    )


@app.route("/", methods=["GET", "POST"])
def index():
    # 管理者自身の希望入力。管理者は締め切り後も編集できる（ロック対象外）。
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = now_jst()
    year, month = resolve_ym(now.year, now.month)
    with closing(get_db()) as conn:
        deadline = get_deadline(conn, year, month)
    return handle_input(
        "shift_form.html", g.user.username, g.user.name,
        year=year, month=month, redirect_endpoint="index", deadline=deadline,
    )


@app.route("/worker", methods=["GET", "POST"])
def worker():
    # スタッフ本人の希望入力。締め切り日以降は読み取り専用。
    if not require_login():
        return redirect(url_for("login"))
    now = now_jst()
    year, month = resolve_ym(now.year, now.month)
    with closing(get_db()) as conn:
        deadline = get_deadline(conn, year, month)
    locked = is_locked_for_staff(deadline)
    if request.method == "POST" and locked:
        flash("締め切り後のため、見るだけです。変更は管理者に伝えてください。")
        return redirect(url_for("worker", year=year, month=month))
    return handle_input(
        "shift_form.html", g.user.username, g.user.name,
        year=year, month=month, redirect_endpoint="worker",
        read_only=locked, deadline=deadline,
    )


@app.route("/staff/<username>", methods=["GET", "POST"])
def staff_edit(username):
    # 管理者が指定スタッフの希望を代理編集（締め切り後も可）。
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = now_jst()
    year, month = resolve_ym(now.year, now.month)
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT username, name FROM users WHERE username=? AND is_active=1",
            (username,),
        ).fetchone()
        deadline = get_deadline(conn, year, month)
    if not row:
        flash("職員が見つかりません。停止中の職員は一覧で確認してください。")
        return redirect(url_for("submissions", year=year, month=month))
    return handle_input(
        "shift_form.html", row[0], row[1],
        year=year, month=month, redirect_endpoint="staff_edit",
        redirect_kwargs={"username": row[0]}, editor_is_admin=True,
        deadline=deadline, log_action_name="staff_shift_edit",
    )


@app.route("/admin")
def admin():
    # N: /admin は管理者専用（V29: 共通ガードに統一＋authz_fail 記録）
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = now_jst()
    year, month = safe_ym(now.year, now.month)
    with closing(get_db()) as conn:
        # JOIN を username 基準に（rename 取りこぼし解消）。表示名・色は users 側の最新を使う
        rows = conn.execute(
            "SELECT s.day, u.name, s.status, u.color, s.remarks "
            "FROM shifts s INNER JOIN users u ON s.username = u.username "
            "WHERE s.year=? AND s.month=?",
            (year, month),
        ).fetchall()
        deadline = get_deadline(conn, year, month)
        # 未提出の有効ユーザー数（締め切り運用の進捗把握用）
        pending = conn.execute(
            "SELECT COUNT(*) FROM users u WHERE u.is_active=1 AND NOT EXISTS ("
            "SELECT 1 FROM shifts s WHERE s.username=u.username "
            "AND s.year=? AND s.month=?)",
            (year, month),
        ).fetchone()[0]
    return render_template(
        "admin.html",
        year=year, month=month,
        cal=calendar.monthcalendar(year, month),
        rows=rows,
        pending=pending,
        deadline_label=deadline_label(deadline),
        locked=is_locked_for_staff(deadline),
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
                # 編集モードでは original_username を権威とし、フォームの username 入力は無視
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
                    # 表示名の重複検査（同 username なら自分自身なので除外）
                    dup = conn.execute(
                        "SELECT username FROM users WHERE name=? AND username != ?",
                        (n, u),
                    ).fetchone()
                    # すべての検証を先に通し、検証通過後にだけ DB を更新する
                    # （検証失敗時に shifts.name だけ先に変わって users と不整合になる事故を防ぐ）
                    if mode == "edit" and not existing:
                        # 編集対象が消えている / ID 改ざんを検知
                        flash("編集対象のユーザーが見つかりません。ID 変更は禁止です（停止 → 削除 → 新規登録の手順で行ってください）")
                    elif mode == "create" and existing:
                        # 重複登録を明示的に拒否（修正したいなら一覧の「修正」を使う）
                        flash(f"そのID（{u}）は既に登録されています。修正する場合は一覧の「修正」ボタンから操作してください")
                    elif r not in ("admin", "worker"):
                        flash("権限の値が不正です")
                    elif not HEX_COLOR_RE.match(col):
                        flash("色コードの形式が不正です（#RRGGBB）")
                    elif not n or len(n) > 32:
                        flash("お名前は1〜32文字で入力してください")
                    elif NAME_FORBIDDEN_RE.search(n):
                        # 表示名は URL パスに入るため / 等を禁止
                        flash("お名前に使えない文字（/ \\ ? # & < > 改行 等）が含まれています")
                    elif dup:
                        flash(f"同じ表示名のユーザー（ID: {dup[0]}）が既に存在します")
                    elif existing and p and not is_valid_password(p, u):
                        flash(password_error(p, u))
                    elif not existing and not is_valid_password(p, u):
                        flash(password_error(p, u))
                    elif existing and existing[1] != r and u == g.user.username:
                        # 自分自身の権限変更を禁止（自己降格による締め出し防止）
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
                        # 最後の有効な管理者は降格できない
                        flash("有効な管理者が最低1人残るよう、最後の管理者を降格することはできません")
                    else:
                        if existing:
                            # 表示名変更時はシフト名も連動（J の根本対応はフェーズ3）
                            if existing[0] != n:
                                conn.execute(
                                    "UPDATE shifts SET name=? WHERE username=?",
                                    (n, u),
                                )
                            if p:
                                # 管理者が新しいパスワードを設定（強制変更は廃止）
                                conn.execute(
                                    "UPDATE users SET password=?, role=?, name=?, color=? "
                                    "WHERE username=?",
                                    (
                                        generate_password_hash(normalize_password(p)),
                                        r, n, col, u,
                                    ),
                                )
                                log_action(conn, "user_edit", target=u, detail={"name": n, "role": r})
                                # 管理者による他人のパスワード設定を専用イベントで記録（再発行運用の証跡）
                                log_action(conn, "admin_password_set", target=u)
                                flash("ユーザー情報を保存しました（新しいパスワードを設定しました）")
                            else:
                                # A: 編集時にパスワード空欄ならパスワードは据え置き
                                conn.execute(
                                    "UPDATE users SET role=?, name=?, color=? WHERE username=?",
                                    (r, n, col, u),
                                )
                                log_action(conn, "user_edit", target=u, detail={"name": n, "role": r})
                                flash("ユーザー情報を保存しました（パスワードは変更なし）")
                        else:
                            # 新規ユーザー登録（強制変更なし。本人がいつでも変更可能）
                            conn.execute(
                                "INSERT INTO users "
                                "(username, password, role, name, is_active, color) "
                                "VALUES (?, ?, ?, ?, 1, ?)",
                                (
                                    u,
                                    generate_password_hash(normalize_password(p)),
                                    r, n, col,
                                ),
                            )
                            log_action(conn, "user_create", target=u, detail={"name": n, "role": r})
                            flash("ユーザーを登録しました。")
                elif action == "toggle":
                    target = conn.execute(
                        "SELECT role, is_active FROM users WHERE username=?",
                        (u,),
                    ).fetchone()
                    # 自分自身の停止禁止 + 最後の有効 admin の停止禁止
                    if u == g.user.username:
                        flash("自分自身を停止することはできません")
                    elif u == "admin":
                        # 既存の固定保護（初期 admin 行）を維持
                        flash("初期管理者は停止できません")
                    elif not target:
                        flash("対象のユーザーが見つかりません")
                    else:
                        current_active = target[1]
                        allow = True
                        if current_active == 1:  # 1 → 0（停止に向かう）
                            if target[0] == "admin":
                                admin_count = conn.execute(
                                    "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
                                ).fetchone()[0]
                                if admin_count <= 1:
                                    flash("最後の有効な管理者を停止することはできません")
                                    allow = False
                        if allow:
                            new_active = 0 if current_active == 1 else 1
                            conn.execute(
                                "UPDATE users SET is_active=? WHERE username=?",
                                (new_active, u),
                            )
                            log_action(conn, "user_toggle", target=u, detail={"is_active": new_active})
                elif action == "delete":
                    # 試用初期は UI から削除ボタンを撤去（manage_users.html）。
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
    # 操作ログの閲覧（管理者専用）。V29: 共通ガードに統一。
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
        raw_rows = conn.execute(
            "SELECT ts, actor, actor_name, action, target, detail, ip "
            "FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (per, offset),
        ).fetchall()
    rows = [(format_jst(row[0]), *row[1:]) for row in raw_rows]
    labels = {
        "login_success": "ログイン成功",
        "login_fail": "ログイン失敗",
        "logout": "ログアウト",
        "csrf_error": "セッション切れ",
        "authz_fail": "権限エラー",
        "password_change": "パスワード変更",
        "user_create": "ユーザー追加",
        "user_edit": "ユーザー修正",
        "user_toggle": "停止・復活",
        "admin_password_set": "パスワード設定（管理者）",
        "request_submit": "希望提出",
        "staff_shift_edit": "希望を代理編集",
        "deadline_set": "締め切り設定",
        "backup_check": "外部保存の確認",
    }
    return render_template(
        "logs.html",
        rows=rows,
        page=page,
        total=total,
        has_next=(offset + per < total),
        labels=labels,
    )


@app.route("/submissions")
def submissions():
    # 提出状況の一覧（管理者専用）。shifts から導出し、最終提出時刻は audit_log から取得。
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = now_jst()
    year, month = safe_ym(now.year, now.month)
    ym = f"{year}-{month:02d}"
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
        # 最終更新: 本人提出(request_submit)と管理者代理編集(staff_shift_edit)の両方を集計。
        # target は新形式 "YYYY-MM:username"、旧データは "YYYY-MM"(actor=本人) も拾う。
        last_at = {}
        for ts, target, actor in conn.execute(
            "SELECT ts, target, actor FROM audit_log "
            "WHERE action IN ('request_submit','staff_shift_edit') "
            "AND (target=? OR target LIKE ?) ORDER BY id",
            (ym, ym + ":%"),
        ).fetchall():
            owner = target.split(":", 1)[1] if ":" in target else actor
            last_at[owner] = ts  # id 昇順 → 最後に上書きされた値が最新
        deadline = get_deadline(conn, year, month)
    items = [
        {
            "username": u[0], "name": u[1], "role": u[2],
            "submitted": u[0] in submitted,
            "ok": ok_counts.get(u[0], 0) or 0,
            "last": format_jst(last_at.get(u[0], "")),
        }
        for u in users
    ]
    pending = sum(1 for it in items if not it["submitted"])
    return render_template(
        "submissions.html", items=items, pending=pending,
        year=year, month=month,
        deadline=deadline or "", deadline_label=deadline_label(deadline),
        locked=is_locked_for_staff(deadline),
        **get_month_links()
    )


@app.route("/deadline", methods=["POST"])
def set_deadline_route():
    # 締め切り日の設定/解除（管理者専用）。空欄なら解除。
    guard = deny_if_not_admin()
    if guard:
        return guard
    now = now_jst()
    year, month = resolve_ym(now.year, now.month)
    raw = (request.form.get("deadline") or "").strip()
    if raw and parse_deadline(raw) is None:
        flash("締め切り日の形式が正しくありません。")
        return redirect(url_for("submissions", year=year, month=month))
    with closing(get_db()) as conn, conn:
        set_deadline(conn, year, month, raw)
        log_action(conn, "deadline_set", target=f"{year}-{month:02d}",
                   detail={"deadline": raw or "(解除)"})
    flash("締め切りを更新しました。" if raw else "締め切りを解除しました。")
    return redirect(url_for("submissions", year=year, month=month))


@app.route("/backup_check", methods=["POST"])
def backup_check():
    # 管理者が「月次の外部保存を確認した」と記録する（メニューの状態パネルから）。
    guard = deny_if_not_admin()
    if guard:
        return guard
    db_manager.record_external_backup_check()
    with closing(get_db()) as conn, conn:
        log_action(conn, "backup_check")
    flash("外部保存の確認を記録しました。")
    return redirect(url_for("menu"))


# 旧「確定シフト」URL は廃止。誤遷移防止のため新しい画面へ案内する。
# 撤去予定: 2026-09 以降のリリースで削除（事前に /logs で /confirm・/confirmed への
# アクセスが無いことを確認してから外す）。
@app.route("/confirm")
@app.route("/confirm/<username>")
def confirm_redirect(username=None):
    guard = deny_if_not_admin()
    if guard:
        return guard
    flash("確定シフトは「提出状況・締め切り」に統合しました。")
    return redirect(url_for("submissions"))


@app.route("/confirmed")
def confirmed_redirect():
    if not require_login():
        return redirect(url_for("login"))
    flash("確定シフトは廃止しました。シフトは入力画面で確認できます。")
    return redirect(url_for("menu"))


@app.route("/change_password", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def change_password():
    # ログイン必須化（未ログインの username 当て攻撃面を撤去）。任意のパスワード変更画面。
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
        normalized_current = normalize_password(p_curr)
        current_matches = bool(
            row
            and (
                check_password_hash(row[0], p_curr)
                or (
                    normalized_current != p_curr
                    and check_password_hash(row[0], normalized_current)
                )
            )
        )
        validation_error = password_error(p_new, u)
        if not current_matches or validation_error:
            return render_template(
                "change_password.html",
                error=(
                    "現在のパスワードが正しくありません"
                    if not current_matches
                    else validation_error
                ),
            )
        with closing(get_db()) as conn, conn:
            conn.execute(
                "UPDATE users SET password=? WHERE username=?",
                (generate_password_hash(normalize_password(p_new)), u),
            )
            # 監査ログ（新旧パスワードは記録しない）
            log_action(conn, "password_change")
        session.clear()
        flash("パスワードを変更しました。再度ログインしてください。")
        return redirect(url_for("login"))
    return render_template("change_password.html")


@app.route("/help")
def help_page():
    # ログイン済みなら役割別、未ログインなら基本のみ表示
    return render_template("help.html")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method == "GET":
        if require_login():
            flash("ログアウトする場合はメニューのボタンを押してください。")
            return redirect(url_for("menu"))
        return redirect(url_for("login"))
    if getattr(g, "user", None):
        safe_log_event("logout")
    session.clear()
    flash("ログアウトしました。")
    return redirect(url_for("login"))


@app.route("/healthz")
def healthz():
    return {"status": "ok"}, 200


@app.route("/readyz")
def readyz():
    try:
        ready = db_manager.ready_check()
    except Exception:
        ready = False
    return ({"status": "ready"}, 200) if ready else ({"status": "unavailable"}, 503)


if __name__ == "__main__":
    # G: 本番では gunicorn 起動を強制し debug 実行を禁止
    if IS_PROD:
        raise RuntimeError("本番では gunicorn 経由で起動してください（debug 実行は禁止）")
    app.run(debug=False)
