from flask import Flask, render_template, request
import calendar
from datetime import datetime
import sqlite3

app = Flask(__name__)

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
# 勤務入力画面
# =====================
@app.route("/", methods=["GET", "POST"])
def index():

    year = request.args.get("year", datetime.now().year)
    month = request.args.get("month", datetime.now().month)

    year = int(year)
    month = int(month)

    cal = calendar.monthcalendar(year, month)

    work_days = []
    for week in cal:
        for i, day in enumerate(week):
            if day != 0 and i in [0, 3, 6]:
                work_days.append(day)

    members = ["田中", "佐藤", "鈴木", "高橋", "伊藤"]

    if request.method == "POST":

        year = int(request.form.get("year"))
        month = int(request.form.get("month"))

        conn = sqlite3.connect("shift.db")
        c = conn.cursor()

        # 上書き処理
        c.execute("""
            DELETE FROM shifts
            WHERE year = ? AND month = ?
        """, (year, month))

        for day in work_days:
            for member in members:
                status = request.form.get(f"{member}_{day}", "休暇")

                c.execute("""
                    INSERT INTO shifts (year, month, day, name, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (year, month, day, member, status))

        conn.commit()
        conn.close()

        return "保存しました！（上書き）"

    return render_template(
        "index.html",
        members=members,
        work_days=work_days,
        year=year,
        month=month
    )

# =====================
# 管理画面
# =====================
@app.route("/admin")
def admin():

    year = request.args.get("year", datetime.now().year)
    month = request.args.get("month", datetime.now().month)

    year = int(year)
    month = int(month)

    conn = sqlite3.connect("shift.db")
    c = conn.cursor()

    c.execute("""
        SELECT year, month, day, name, status
        FROM shifts
        WHERE year = ? AND month = ?
        ORDER BY day, name
    """, (year, month))

    rows = c.fetchall()
    conn.close()

    return render_template(
        "admin.html",
        rows=rows,
        year=year,
        month=month
    )

if __name__ == "__main__":
    app.run(debug=True)
