# Shift-Flow

スタッフがスマホからシフト希望を入力し、管理者が確認・調整できる Flask 製アプリ。

> 設計とセキュリティ対策の経緯は [CODE_REVIEW.md](CODE_REVIEW.md) を参照。

---

## ローカルで動かす

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

> Windows で `python3` が無い場合は `python` でも可。
> 以降の例も `python3` で書いていますが、適宜読み替えてください。

ブラウザで http://localhost:5000 を開く。
初回起動時、`admin` の初期パスワードがコンソールに表示される（控えておくこと）。
初回ログイン時はパスワード変更画面に自動的に誘導される（変更まで他の画面に進めない）。

---

## 本番デプロイ（HTTPS 必須）

### 1. 環境変数を設定

```bash
export APP_ENV=production
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export SHIFT_DB_PATH=/var/lib/shift-flow/shift.db
export ADMIN_INIT_PASSWORD=（長いランダム文字列）

# Caddy / Nginx の後ろで動かす場合は追加
export TRUSTED_PROXY_HOPS=1
```

> **`ADMIN_INIT_PASSWORD` を環境変数で渡せばランダム生成のログ出力は出ません**（V6）。
> 環境変数で渡さずランダム生成された場合は、ログを 1 度だけ控えたら必ず
> `journalctl --vacuum-time=…` や該当ログファイル削除でログから消去してください。

### 2. データディレクトリのパーミッションを設定（V7）

DB ファイルにはパスワードハッシュ + 備考が含まれます。他ユーザーから読めない設定が必須。

```bash
# 起動前に
sudo install -d -m 700 -o $(whoami) /var/lib/shift-flow

# 起動後（DB ファイルが作られたら）
chmod 600 /var/lib/shift-flow/shift.db*
```

systemd unit を使う場合は `UMask=0077` を `[Service]` セクションに併記推奨。

### 3. gunicorn で起動

```bash
gunicorn -w 1 -b 127.0.0.1:8000 app:app
```

> **`-w 1` を推奨する理由**（V10）: レート制限のカウンタは既定の `memory://` ストレージだと
> worker ごとに別カウンタになり、`-w 4` だと 1 分 10 回制限が実質 1 分 40 回になります。
> worker を増やしたい場合は `RATELIMIT_STORAGE_URI=redis://...` を設定してください
> （別途 `pip install redis` が必要）。
>
> `app.run` や `python3 app.py` での本番起動は禁止。`APP_ENV=production` で例外停止します。

### 4. HTTPS で公開

**Caddy の例**：
```caddyfile
shift.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

**PaaS（Render / Railway / Fly.io）** なら自動 HTTPS が付く。

---

## 環境変数一覧

| 変数 | 既定 | 説明 |
|------|------|------|
| `SECRET_KEY` | （本番必須） | セッション署名鍵。未設定なら本番起動失敗 |
| `APP_ENV` | `development` | 本番は `production` を指定 |
| `SHIFT_DB_PATH` | `instance/shift.db` | DB ファイルの場所。**本番は絶対パス必須** |
| `ADMIN_INIT_PASSWORD` | （ランダム生成） | 初回起動時の admin パスワード。設定すればログ出力なし |
| `TRUSTED_PROXY_HOPS` | `0` | リバプロ段数。Caddy/Nginx 経由なら `1`、直接公開なら `0` |
| `RATELIMIT_STORAGE_URI` | `memory://` | worker 複数なら `redis://localhost:6379/0`（要 `pip install redis`） |

---

## バックアップ

WAL モード稼働中は **必ず** `sqlite3 .backup` を使う。`cp shift.db` は壊れたバックアップになる。

```bash
sqlite3 /var/lib/shift-flow/shift.db ".backup '/path/to/backup-$(date +%F).db'"
```

cron で日次実行を推奨。バックアップファイル自体も `chmod 600` で保護。

### 復元

サービス停止 → 既存の `shift.db` / `shift.db-wal` / `shift.db-shm` を削除 → バックアップを `SHIFT_DB_PATH` の位置に配置 → サービス起動。

---

## ユーザーの完全削除（管理 CLI 経由）

UI からの削除ボタンは試用初期は撤去しています（誤操作による不可逆事故の防止）。退職や休職は
「停止」で十分です（ログインできなくなり、シフト履歴は残ります）。

どうしても物理削除が必要な場合のみ、以下の手順で行ってください：

```bash
# 1. サービス停止
sudo systemctl stop shift-flow   # 環境に応じて

# 2. バックアップ
sqlite3 /var/lib/shift-flow/shift.db ".backup '/path/to/backup-pre-delete.db'"

# 3. 対象ユーザーのシフト履歴と本体を削除
sqlite3 /var/lib/shift-flow/shift.db \
  "DELETE FROM shifts WHERE name=(SELECT name FROM users WHERE username='対象ID'); \
   DELETE FROM users WHERE username='対象ID';"

# 4. サービス再開
sudo systemctl start shift-flow
```

---

## 旧 DB（Phase 1 以前）から移行

平文パスワードが残った旧 DB はそのままだとログイン不能。一度 admin を作り直す：

```bash
cp shift.db shift.db.legacy.backup
sqlite3 shift.db "DELETE FROM users WHERE username='admin';"

export ADMIN_INIT_PASSWORD=（新しい長いランダム文字列）
# 通常通り起動 → admin でログインし /manage_users から職員を再登録
```

職員のシフト履歴は表示名で紐づくので、再登録時に **旧と同じ表示名** を使えば残る。

---

## テストの実行

開発用依存をインストール後、`pytest` を実行：

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

`tests/` 配下にユニットテスト一式があります。

---

## トラブルシュート

| 症状 | 対処 |
|------|------|
| `SECRET_KEY が未設定です` で起動失敗 | `export SECRET_KEY=...` を設定 |
| admin の初期パスワードが分からない | 起動ログを確認。失った場合は上記「旧 DB から移行」と同じ手順 |
| ログインで 429 が返る | レート制限（1分10回）。1分待つ |
| `TRUSTED_PROXY_HOPS は非負整数...` で停止 | 値を `0` か `1` に修正 |
| `'redis' prerequisite not available` | `pip install redis` |
| 職員に「全体のシフト確認」が出ない | 仕様。フェーズ3 で確定シフトを実装後に開放予定 |
| パスワード変更画面から他画面に進めない | `must_change_password` 強制中。新しいパスワードを設定すれば解除されます |
| 送信後にブラウザ更新で「翌月分も提出しますか？」が再表示 | 修正済（V5）。再発時は強制リロード（Cmd/Ctrl+Shift+R）|
