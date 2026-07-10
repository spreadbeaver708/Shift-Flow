#!/bin/sh
# 復元リハーサル: バックアップDBを「複製」で開き、中身が戻ることを確認する練習。
#
#   使い方:  sh scripts/restore_rehearsal.sh <バックアップファイル.db>
#   例:      sh scripts/restore_rehearsal.sh ~/Downloads/monthly-202607.db
#
# 本番や instance/shift.db には一切触れません。バックアップ元のファイルも読み取るだけです。
# 複製は instance/restore-rehearsal/ に作られます（git 管理外）。
set -eu

if [ ! -f app.py ]; then
    echo "このスクリプトはリポジトリのフォルダ（app.py がある場所）で実行してください。"
    echo "例: cd Shift-Flow && sh scripts/restore_rehearsal.sh <バックアップファイル.db>"
    exit 1
fi

if [ $# -ne 1 ] || [ ! -f "${1:-}" ]; then
    echo "使い方: sh scripts/restore_rehearsal.sh <バックアップファイル.db>"
    echo "  Render から手元に保存した monthly-*.db などを指定してください。"
    exit 1
fi

SRC=$1
WORK=instance/restore-rehearsal
mkdir -p "$WORK"
DEST="$WORK/shift.db"

# 過去のリハーサルの残骸（DB本体とWAL/SHM）を消してから複製する。
# 古い -wal/-shm を新しいDBに適用してはいけない（README「バックアップ」参照）。
rm -f "$DEST" "$DEST-wal" "$DEST-shm"
cp "$SRC" "$DEST"
echo "複製しました: $SRC -> $DEST"
echo ""

python3 - "$DEST" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
conn = sqlite3.connect(path)

ok = conn.execute("PRAGMA integrity_check").fetchone()[0]
print(f"1) 健全性チェック (integrity_check): {ok}")
if ok != "ok":
    print("   ! このバックアップは壊れている可能性があります。別のバックアップで試してください。")
    sys.exit(1)

version = conn.execute("PRAGMA user_version").fetchone()[0]
print(f"2) スキーマバージョン: {version}")

tables = {row[0] for row in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'")}
print("3) 中身の件数:")
for table, label in [("users", "利用者"), ("shifts", "シフト希望"),
                     ("deadlines", "締め切り"), ("audit_log", "操作ログ")]:
    if table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608 - table名は固定リスト
        print(f"   - {label} ({table}): {count} 件")
    else:
        print(f"   ! テーブル {table} がありません")
conn.close()
PY

echo ""
echo "4) 次のコマンドで複製DBを使ってアプリを起動し、実際の画面で確認してください:"
echo ""
# ポート5050を使う: macOS は AirPlay が 5000 番を使っていることがあり、
# Flask 既定の 5000 だと「起動できない・変な応答が返る」で初心者が詰まるため。
echo "   SHIFT_DB_PATH=$PWD/$DEST python3 -m flask --app app run --port 5050"
echo ""
echo "   ブラウザで http://127.0.0.1:5050 を開き、いつものIDでログインして"
echo "   利用者・シフト希望・締め切り・操作ログが戻っていることを確認します。"
echo "   確認できたら Ctrl+C で止めてください。これで復元リハーサル完了です。"
echo "   （確認日を docs/ROADMAP.md の記録欄に書いておきましょう）"
