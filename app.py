from flask import Flask, render_template, request, redirect, url_for, session
import calendar
from datetime import datetime
import sqlite3

app = Flask(__name__)
app.secret_key = "cafe_shift_secret_key"

# カレンダーを日曜日始まりに設定
calendar.setfirstweekday(calendar.SUNDAY)

def get_db():
    conn = sqlite3.connect("shift.db")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # シフト用
    c.execute("""CREATE TABLE IF NOT EXISTS shifts 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, month INTEGER, day INTEGER, name TEXT, status TEXT)""")
    # ユーザー用
    c.execute("""CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, role TEXT, name TEXT, is_active INTEGER DEFAULT 1)""")
    
    # 初期管理者登録
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO users VALUES ('admin', 'admin123', 'admin', '管理者', 1)")
    conn.commit()
    conn.close()

init_db()

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username, password = request.form.get("username"), request.form.get("password")
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=? AND is_active=1", (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            session.update({"username": user[0], "role": user[2], "name": user[3]})
            return redirect(url_for("menu"))
        return render_template("login.html", error="ログイン失敗")
    return render_template("login.html")

@app.route("/menu")
def menu():
    if "username" not in session: return redirect(url_for("login"))
    return render_template("menu.html")

# 管理者自身の入力
@app.route("/", methods=["GET", "POST"])
def index():
    if "role" not in session or session["role"] != "admin": return redirect(url_for("login"))
    return handle_shift_input("index.html")

# 職員の入力
@app.route("/worker/<name>", methods=["GET", "POST"])
def worker(name):
    if "username" not in session or session["name"] != name: return redirect(url_for("login"))
    return handle_shift_input("worker.html", name)

def handle_shift_input(template, name=None):
    name = name or session["name"]
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    cal = calendar.monthcalendar(year, month)

    if request.method == "POST":
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM shifts WHERE year=? AND month=? AND name=?", (year, month, name))
        # 日(0), 月(1), 木(4) を保存対象とする
        for week in cal:
            for i, day in enumerate(week):
                if day != 0 and i in [0, 1, 4]:
                    status = request.form.get(f"day_{day}", "×")
                    c.execute("INSERT INTO shifts (year, month, day, name, status) VALUES (?,?,?,?,?)", (year, month, day, name, status))
        conn.commit()
        conn.close()
        return redirect(url_for("menu"))
    return render_template(template, name=name, year=year, month=month, cal=cal)

@app.route("/admin")
def admin():
    if "username" not in session: return redirect(url_for("login"))
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT day, name, status FROM shifts WHERE year=? AND month=?", (year, month))
    rows = c.fetchall()
    conn.close()
    return render_template("admin.html", year=year, month=month, cal=calendar.monthcalendar(year, month), rows=rows)

@app.route("/manage_users", methods=["GET", "POST"])
def manage_users():
    if "role" not in session or session["role"] != "admin": return redirect(url_for("login"))
    conn = get_db()
    c = conn.cursor()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            try: c.execute("INSERT INTO users VALUES (?,?,?,?,1)", (request.form.get("u"), request.form.get("p"), request.form.get("r"), request.form.get("n")))
            except: pass
        elif action == "toggle":
            u, s = request.form.get("u"), int(request.form.get("s"))
            if u != "admin": c.execute("UPDATE users SET is_active=? WHERE username=?", (0 if s==1 else 1, u))
        conn.commit()
    c.execute("SELECT username, role, name, is_active FROM users")
    users = c.fetchall()
    conn.close()
    return render_template("manage_users.html", users=users)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)