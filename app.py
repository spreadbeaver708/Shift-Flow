from flask import Flask, render_template, request, redirect, url_for, session
import calendar
from datetime import datetime
import sqlite3

app = Flask(__name__)
app.secret_key = "your_secret_key_here"  # セッション用

# =====================
# データベース初期化
# =====================
def init_db():
    conn = sqlite3.connect("shift.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            name TEXT,
            status TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# =====================
# ユーザー情報（簡易版）
# =====================
users = {
    "admin": {"password": "admin123", "role": "admin", "name": None},
    "tanaka": {"password": "1234", "role": "worker", "name": "田中"},
    "sato": {"password": "1234", "role": "worker", "name": "佐藤"},
    "suzuki": {"password": "1234", "role": "worker", "name": "鈴木"},
}

# =====================
# ログイン画面
# =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = users.get(username)
        if user and user["password"] == password:
            session["username"] = username
            session["role"] = user["role"]
            session["name"] = user["name"]
            if user["role"] == "admin":
                return redirect(url_for("admin"))
            else:
                return redirect(url_for("worker", name=user["name"]))
        else:
            error = "ユーザー名またはパスワードが間違っています"
            return render_template("login.html", error=error)
    return render_template("login.html")

# =====================
# ログアウト
# =====================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =====================
# 管理入力画面（全員まとめて）
# =====================
@app.route("/", methods=["GET", "POST"])
def index():
    if "role" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    year = request.args.get("year", datetime.now().year)
    month = request.args.get("month", datetime.now().month)
    year = int(year)
    month = int(month)

    cal = calendar.monthcalendar(year, month)
    work_days = [day for week in cal for i, day in enumerate(week) if day != 0 and i in [0,3,6]]

    members = ["田中", "佐藤", "鈴木", "高橋", "伊藤"]

    if request.method == "POST":
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))

        conn = sqlite3.connect("shift.db")
        c = conn.cursor()

        c.execute("DELETE FROM shifts WHERE year=? AND month=?", (year, month))

        for day in work_days:
            for member in members:
                status = request.form.get(f"{member}_{day}", "休暇")
                c.execute("INSERT INTO shifts (year, month, day, name, status) VALUES (?, ?, ?, ?, ?)",
                          (year, month, day, member, status))

        conn.commit()
        conn.close()

        return "保存しました！（上書き）"

    return render_template("index.html", members=members, work_days=work_days, year=year, month=month)

# =====================
# 管理確認画面
# =====================
@app.route("/admin")
def admin():
    if "role" not in session or session["role"] != "admin":
        return redirect(url_for("login"))

    year = request.args.get("year", datetime.now().year)
    month = request.args.get("month", datetime.now().month)
    year = int(year)
    month = int(month)

    conn = sqlite3.connect("shift.db")
    c = conn.cursor()
    c.execute("SELECT year, month, day, name, status FROM shifts WHERE year=? AND month=? ORDER BY day, name",
              (year, month))
    rows = c.fetchall()
    conn.close()

    return render_template("admin.html", rows=rows, year=year, month=month)

# =====================
# 作業者入力画面（個別）
# =====================
@app.route("/worker/<name>", methods=["GET", "POST"])
def worker(name):
    if "role" not in session or session["role"] != "worker" or session["name"] != name:
        return redirect(url_for("login"))

    year = request.args.get("year", datetime.now().year)
    month = request.args.get("month", datetime.now().month)
    year = int(year)
    month = int(month)

    cal = calendar.monthcalendar(year, month)

    if request.method == "POST":
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
        cal = calendar.monthcalendar(year, month)

        conn = sqlite3.connect("shift.db")
        c = conn.cursor()
        c.execute("DELETE FROM shifts WHERE year=? AND month=? AND name=?", (year, month, name))

        for week in cal:
            for i, day in enumerate(week):
                if day != 0 and i in [0,1,4]:
                    status = request.form.get(f"day_{day}", "休暇")
                    c.execute("INSERT INTO shifts (year, month, day, name, status) VALUES (?, ?, ?, ?, ?)",
                              (year, month, day, name, status))

        conn.commit()
        conn.close()

        return f"{name} のシフトを保存しました"

    return render_template("worker.html", name=name, year=year, month=month, cal=cal)

# =====================
# サーバー起動
# =====================
if __name__ == "__main__":
    app.run(debug=True)
