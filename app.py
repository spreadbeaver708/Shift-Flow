import os
import re
import secrets
import sqlite3
import calendar
from contextlib import closing
from datetime import datetime, timedelta
from types import SimpleNamespace

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, g, abort,
)
from flask_wtf import CSRFProtect
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

# H: セッションCookie属性。SECURE は HTTPS本番限定。
app.config.update(
    SESSION_COOKIE_SECURE=IS_PROD,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
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

# I: ログイン試行レート制限
# Codex#4: storage_uri を明示。複数 worker でレート制限を厳密に共有したい場合は
# RATELIMIT_STORAGE_URI=redis://... のような共有ストレージを指定する。
# 未指定（memory://）の場合は worker ごとに別カウンタになる点に注意（README 参照）。
limiter = Limiter(
    get_remote_address,
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
                "(username, password, role, name, is_active, color) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                ("admin", generate_password_hash(init_pw), "admin", "管理者", "#2196F3"),
            )
            if cur.rowcount > 0 and is_random:
                print("[init] ADMIN_INIT_PASSWORD 未設定のためランダム生成しました。")
                print(f"[init] admin 初期パスワード（一度だけ表示）: {init_pw}")
                print("[init] 初回ログイン後、/change_password で必ず変更してください。")
            elif cur.rowcount > 0:
                print("[init] admin ユーザーを作成しました（ADMIN_INIT_PASSWORD を使用）")


init_db()
print(f"[init] DB_PATH={DB_PATH}")


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


def is_valid_password(p):
    return p is not None and len(p) >= 4 and p.isalnum()


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
    g.user = None
    u = session.get("username")
    if not u:
        return
    with closing(get_db()) as conn:
        row = conn.execute(
            "SELECT username, role, name, is_active FROM users WHERE username=?", (u,)
        ).fetchone()
    if not row or row[3] == 0:
        # 削除または停止済み → 旧セッションを破棄
        session.clear()
        return
    g.user = SimpleNamespace(username=row[0], role=row[1], name=row[2])


@app.context_processor
def inject_current_user():
    # テンプレも session['role'] ではなく current_user.role を使うように統一
    return {"current_user": getattr(g, "user", None)}


def require_login():
    return g.user is not None


def require_admin():
    return g.user is not None and g.user.role == "admin"


# =====================
# ルート定義
# =====================
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
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
            session.clear()
            session["username"] = row[0]
            session["role"] = row[2]
            session["name"] = row[3]
            return redirect(url_for("menu"))
        return render_template("login.html", error="IDまたはパスワードが正しくありません")
    return render_template("login.html")


@app.route("/menu")
def menu():
    if not require_login():
        return redirect(url_for("login"))
    links = get_month_links()
    with closing(get_db()) as conn:
        exists = conn.execute(
            "SELECT 1 FROM shifts WHERE year=? AND month=? AND name=?",
            (links["next_y"], links["next_m"], g.user.name),
        ).fetchone()
    return render_template("menu.html", unsubmitted=not exists, next_m=links["next_m"])


def handle_input(template, name=None):
    name = name or g.user.name
    now = datetime.now()
    year, month = safe_ym(now.year, now.month)
    cal = calendar.monthcalendar(year, month)

    if request.method == "POST":
        with closing(get_db()) as conn, conn:
            conn.execute("DELETE FROM shifts WHERE year=? AND month=? AND name=?", (year, month, name))
            for week in cal:
                for i, day in enumerate(week):
                    if day != 0 and i in [0, 1, 4]:  # 日・月・木
                        status = request.form.get(f"day_{day}", "×")
                        if status not in ("〇", "×"):
                            status = "×"
                        remark = (request.form.get(f"remark_{day}", "") or "")[:REMARK_MAX_LEN]
                        conn.execute(
                            "INSERT INTO shifts (year, month, day, name, status, remarks) "
                            "VALUES (?,?,?,?,?,?)",
                            (year, month, day, name, status, remark),
                        )
        if template == "index.html":
            return redirect(url_for("index", year=year, month=month, submitted="true"))
        return redirect(url_for("worker", name=name, year=year, month=month, submitted="true"))

    with closing(get_db()) as conn:
        existing = {
            row[0]: {"status": row[1], "remark": row[2]}
            for row in conn.execute(
                "SELECT day, status, remarks FROM shifts WHERE year=? AND month=? AND name=?",
                (year, month, name),
            ).fetchall()
        }
    return render_template(
        template, name=name, year=year, month=month, cal=cal, shifts=existing, **get_month_links()
    )


@app.route("/", methods=["GET", "POST"])
def index():
    if not require_admin():
        return redirect(url_for("login"))
    return handle_input("index.html")


@app.route("/worker/<name>", methods=["GET", "POST"])
def worker(name):
    if not require_login() or g.user.name != name:
        return redirect(url_for("login"))
    return handle_input("worker.html", name)


@app.route("/admin")
def admin():
    # N: フェーズ1 では /admin を管理者専用に
    if not require_login():
        return redirect(url_for("login"))
    if not require_admin():
        abort(403)
    now = datetime.now()
    year, month = safe_ym(now.year, now.month)
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT s.day, s.name, s.status, u.color, s.remarks "
            "FROM shifts s INNER JOIN users u ON s.name = u.name "
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
    if not require_admin():
        return redirect(url_for("login"))
    with closing(get_db()) as conn:
        if request.method == "POST":
            with conn:
                action = request.form.get("action")
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
                    if r not in ("admin", "worker"):
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
                        flash("パスワードは4文字以上の英数字で入力してください")
                    elif not existing and not is_valid_password(p):
                        flash("パスワードは4文字以上の英数字で入力してください")
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
                                conn.execute(
                                    "UPDATE users SET password=?, role=?, name=?, color=? "
                                    "WHERE username=?",
                                    (generate_password_hash(p), r, n, col, u),
                                )
                                flash("ユーザー情報を保存しました")
                            else:
                                # A: 編集時にパスワード空欄ならパスワードは据え置き
                                conn.execute(
                                    "UPDATE users SET role=?, name=?, color=? WHERE username=?",
                                    (r, n, col, u),
                                )
                                flash("ユーザー情報を保存しました（パスワードは変更なし）")
                        else:
                            conn.execute(
                                "INSERT INTO users "
                                "(username, password, role, name, is_active, color) "
                                "VALUES (?, ?, ?, ?, 1, ?)",
                                (u, generate_password_hash(p), r, n, col),
                            )
                            flash("ユーザーを登録しました")
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
                            conn.execute(
                                "UPDATE users SET is_active=? WHERE username=?",
                                (0 if s == 1 else 1, u),
                            )
                elif action == "delete":
                    # Codex(後追加)#1: 自分自身の削除禁止 + 最後の有効 admin の削除禁止
                    if u == g.user.username:
                        flash("自分自身を削除することはできません")
                    elif u == "admin":
                        # 既存の固定保護を維持
                        pass
                    else:
                        target = conn.execute(
                            "SELECT name, role, is_active FROM users WHERE username=?", (u,)
                        ).fetchone()
                        allow = True
                        if target and target[1] == "admin" and target[2] == 1:
                            admin_count = conn.execute(
                                "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
                            ).fetchone()[0]
                            if admin_count <= 1:
                                flash("最後の有効な管理者を削除することはできません")
                                allow = False
                        if allow and target:
                            conn.execute("DELETE FROM shifts WHERE name=?", (target[0],))
                            conn.execute("DELETE FROM users WHERE username=?", (u,))
        # A: パスワード列は読み出さない（HTMLに渡さない）
        users = conn.execute(
            "SELECT username, role, name, is_active, color FROM users"
        ).fetchall()
    return render_template("manage_users.html", users=users)


@app.route("/change_password", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def change_password():
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p_curr = request.form.get("password_current") or ""
        p_new = request.form.get("password_new") or ""
        with closing(get_db()) as conn:
            row = conn.execute(
                "SELECT username, password FROM users WHERE username=? AND is_active=1",
                (u,),
            ).fetchone()
        if not row or not check_password_hash(row[1], p_curr) or not is_valid_password(p_new):
            return render_template(
                "change_password.html",
                error="現在の情報が間違っているか、新しいパスワードが正しくありません",
            )
        with closing(get_db()) as conn, conn:
            conn.execute(
                "UPDATE users SET password=? WHERE username=?",
                (generate_password_hash(p_new), u),
            )
        flash("パスワードを変更しました。再度ログインしてください。")
        return redirect(url_for("login"))
    return render_template("change_password.html")


@app.route("/help")
def help_page():
    # ログイン済みなら役割別、未ログインなら基本のみ表示
    return render_template("help.html")


@app.route("/logout")
def logout():
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
