from flask import Flask, render_template, request, redirect, url_for, session, flash
import calendar
from datetime import datetime, timedelta
import sqlite3

app = Flask(__name__)
# セッションの暗号化キー
app.secret_key = "cafe_shift_ultra_final_complete_v11"

# カレンダーを日曜日始まりに固定
calendar.setfirstweekday(calendar.SUNDAY)

def get_db():
    return sqlite3.connect("shift.db")

# =====================
# データベース初期化
# =====================
def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, month INTEGER, day INTEGER, name TEXT, status TEXT, remarks TEXT DEFAULT '')")
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT, name TEXT, is_active INTEGER DEFAULT 1, color TEXT DEFAULT '#e8f5e9')")
    
    # adminの保護と復旧
    c.execute("SELECT * FROM users WHERE username='admin'")
    if c.fetchone():
        c.execute("UPDATE users SET role='admin', is_active=1 WHERE username='admin'")
    else:
        c.execute("INSERT INTO users VALUES ('admin', 'admin123', 'admin', '管理者', 1, '#2196F3')")
    
    # ユーザー名が変更されたり削除された場合に残った不要なシフトデータを削除
    c.execute("DELETE FROM shifts WHERE name NOT IN (SELECT name FROM users)")
    
    conn.commit()
    conn.close()

init_db()

# =====================
# ヘルパー関数
# =====================
def get_month_links():
    """今月と翌月の年月を取得して辞書で返す"""
    now = datetime.now()
    next_date = datetime(now.year, now.month, 1) + timedelta(days=32)
    return {
        "now_y": now.year, "now_m": now.month, 
        "next_y": next_date.year, "next_m": next_date.month
    }

def is_valid_password(p):
    """パスワードのバリデーション（4文字以上英数）"""
    return len(p) >= 4 and p.isalnum()

# =====================
# ルート定義
# =====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form.get("username"), request.form.get("password")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=? AND is_active=1", (u, p)).fetchone()
        conn.close()
        if user:
            session.update({"username": user[0], "role": user[2], "name": user[3]})
            return redirect(url_for("menu"))
        return render_template("login.html", error="IDまたはパスワードが正しくありません")
    return render_template("login.html")

@app.route("/menu")
def menu():
    if "username" not in session: return redirect(url_for("login"))
    links = get_month_links()
    conn = get_db()
    # 翌月分のシフトが提出されているかチェック
    exists = conn.execute("SELECT 1 FROM shifts WHERE year=? AND month=? AND name=?", (links["next_y"], links["next_m"], session["name"])).fetchone()
    conn.close()
    return render_template("menu.html", unsubmitted=not exists, next_m=links["next_m"])

def handle_input(template, name=None):
    """管理者用(index)と職員用(worker)の共通入力ロジック"""
    name = name or session["name"]
    year = request.args.get("year", datetime.now().year, type=int)
    month = request.args.get("month", datetime.now().month, type=int)
    cal = calendar.monthcalendar(year, month)
    
    if request.method == "POST":
        conn = get_db()
        conn.execute("DELETE FROM shifts WHERE year=? AND month=? AND name=?", (year, month, name))
        for week in cal:
            for i, day in enumerate(week):
                if day != 0 and i in [0, 1, 4]: # 日・月・木
                    status = request.form.get(f"day_{day}", "×")
                    remark = request.form.get(f"remark_{day}", "")
                    conn.execute("INSERT INTO shifts (year, month, day, name, status, remarks) VALUES (?,?,?,?,?,?)", (year, month, day, name, status, remark))
        conn.commit()
        conn.close()
        
        # ★ここを修正：メニューに戻らず、?submitted=true を付けて同じ画面を再表示する
        # 管理者(index.html)か職員(worker.html)かを判定
        if template == "index.html":
            return redirect(url_for("index", year=year, month=month, submitted="true"))
        else:
            return redirect(url_for("worker", name=name, year=year, month=month, submitted="true"))

    conn = get_db()
    existing = {row[0]: {'status': row[1], 'remark': row[2]} for row in conn.execute("SELECT day, status, remarks FROM shifts WHERE year=? AND month=? AND name=?", (year, month, name)).fetchall()}
    conn.close()
    
    # 全てのテンプレート変数を渡す
    return render_template(template, name=name, year=year, month=month, cal=cal, shifts=existing, **get_month_links())

@app.route("/", methods=["GET", "POST"])
def index():
    if "role" not in session or session["role"] != "admin": return redirect(url_for("login"))
    return handle_input("index.html")

@app.route("/worker/<name>", methods=["GET", "POST"])
def worker(name):
    if "username" not in session or session["name"] != name: return redirect(url_for("login"))
    return handle_input("worker.html", name)

@app.route("/admin")
def admin():
    if "username" not in session: return redirect(url_for("login"))
    year = request.args.get("year", datetime.now().year, type=int)
    month = request.args.get("month", datetime.now().month, type=int)
    conn = get_db()
    rows = conn.execute("""
        SELECT s.day, s.name, s.status, u.color, s.remarks 
        FROM shifts s 
        INNER JOIN users u ON s.name = u.name 
        WHERE s.year=? AND s.month=?
    """, (year, month)).fetchall()
    conn.close()
    return render_template("admin.html", year=year, month=month, cal=calendar.monthcalendar(year, month), rows=rows, **get_month_links())

@app.route("/manage_users", methods=["GET", "POST"])
def manage_users():
    if "role" not in session or session["role"] != "admin": return redirect(url_for("login"))
    conn = get_db()
    if request.method == "POST":
        action, u = request.form.get("action"), request.form.get("username")
        if action == "add":
            p, n, r, col = request.form.get("password"), request.form.get("name"), request.form.get("role"), request.form.get("color")
            if is_valid_password(p):
                # 名前変更時の連動
                old_user = conn.execute("SELECT name FROM users WHERE username=?", (u,)).fetchone()
                if old_user and old_user[0] != n:
                    conn.execute("UPDATE shifts SET name=? WHERE name=?", (n, old_user[0]))
                conn.execute("REPLACE INTO users VALUES (?,?,?,?,?,?)", (u, p, r, n, 1, col))
                conn.commit()
                flash("ユーザー情報を保存しました")
            else: flash("パスワードは4文字以上の英数字で入力してください")
        elif action == "toggle":
            s = int(request.form.get("current_status"))
            if u != "admin": 
                conn.execute("UPDATE users SET is_active=? WHERE username=?", (0 if s==1 else 1, u))
                conn.commit()
        elif action == "delete":
            if u != 'admin':
                user_res = conn.execute("SELECT name FROM users WHERE username=?", (u,)).fetchone()
                if user_res:
                    conn.execute("DELETE FROM shifts WHERE name=?", (user_res[0],))
                conn.execute("DELETE FROM users WHERE username=?", (u,))
                conn.commit()
    users = conn.execute("SELECT username, password, role, name, is_active, color FROM users").fetchall()
    conn.close()
    return render_template("manage_users.html", users=users)

@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if request.method == "POST":
        u, p_curr, p_new = request.form.get("username"), request.form.get("password_current"), request.form.get("password_new")
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (u, p_curr)).fetchone()
        if not user or not is_valid_password(p_new):
            conn.close()
            return render_template("change_password.html", error="現在の情報が間違っているか、新しいパスワードが正しくありません")
        conn.execute("UPDATE users SET password=? WHERE username=?", (p_new, u))
        conn.commit()
        conn.close()
        flash("パスワードを変更しました。再度ログインしてください。")
        return redirect(url_for("login"))
    return render_template("change_password.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)