from flask import Flask, render_template, request, redirect, url_for, session
import calendar
from datetime import datetime, timedelta
import sqlite3

app = Flask(__name__)
app.secret_key = "cafe_shift_system_perfect_final"

# 日曜日始まりに設定
calendar.setfirstweekday(calendar.SUNDAY)

def get_db():
    return sqlite3.connect("shift.db")

def init_db():
    conn = get_db()
    c = conn.cursor()
    # テーブル作成と自動修復
    c.execute("CREATE TABLE IF NOT EXISTS shifts (id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, month INTEGER, day INTEGER, name TEXT, status TEXT, remarks TEXT DEFAULT '')")
    c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT, name TEXT, is_active INTEGER DEFAULT 1, color TEXT DEFAULT '#e8f5e9')")
    try: c.execute("ALTER TABLE shifts ADD COLUMN remarks TEXT DEFAULT ''")
    except: pass
    try: c.execute("ALTER TABLE users ADD COLUMN color TEXT DEFAULT '#e8f5e9'")
    except: pass
    if not c.execute("SELECT * FROM users WHERE username='admin'").fetchone():
        c.execute("INSERT INTO users VALUES ('admin', 'admin123', 'admin', '管理者', 1, '#2196F3')")
    conn.commit()
    conn.close()

init_db()

def get_month_links():
    now = datetime.now()
    next_date = datetime(now.year, now.month, 1) + timedelta(days=32)
    return {"now_y": now.year, "now_m": now.month, "next_y": next_date.year, "next_m": next_date.month}

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
    return render_template("menu.html")

def handle_input(template, name=None):
    name = name or session["name"]
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    cal = calendar.monthcalendar(year, month)
    if request.method == "POST":
        conn = get_db()
        conn.execute("DELETE FROM shifts WHERE year=? AND month=? AND name=?", (year, month, name))
        for week in cal:
            for i, day in enumerate(week):
                if day != 0 and i in [0, 1, 4]:
                    status = request.form.get(f"day_{day}", "×")
                    remark = request.form.get(f"remark_{day}", "")
                    conn.execute("INSERT INTO shifts (year, month, day, name, status, remarks) VALUES (?,?,?,?,?,?)", (year, month, day, name, status, remark))
        conn.commit()
        conn.close()
        return redirect(url_for("menu"))
    conn = get_db()
    existing = {row[0]: {'status': row[1], 'remark': row[2]} for row in conn.execute("SELECT day, status, remarks FROM shifts WHERE year=? AND month=? AND name=?", (year, month, name)).fetchall()}
    conn.close()
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
    year = int(request.args.get("year", datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    conn = get_db()
    rows = conn.execute("SELECT s.day, s.name, s.status, u.color, s.remarks FROM shifts s LEFT JOIN users u ON s.name = u.name WHERE s.year=? AND s.month=?", (year, month)).fetchall()
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
            try: conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?)", (u, p, r, n, 1, col)); conn.commit()
            except: pass
        elif action == "toggle":
            s = int(request.form.get("current_status"))
            if u != "admin": conn.execute("UPDATE users SET is_active=? WHERE username=?", (0 if s==1 else 1, u)); conn.commit()
        elif action == "delete":
            if u != "admin": conn.execute("DELETE FROM users WHERE username=?", (u,)); conn.commit()
    users = conn.execute("SELECT username, role, name, is_active, color FROM users").fetchall()
    conn.close()
    return render_template("manage_users.html", users=users)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/health")
def health():
    return "OK"

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
