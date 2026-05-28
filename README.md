# Shift-Flow

スタッフがスマホからシフト希望を入力し、管理者が確認・調整できる Flask 製アプリ。

> 設計とセキュリティ対策の経緯は [CODE_REVIEW.md](CODE_REVIEW.md) を参照。

---

## ローカルで動かす

```bash
pip install -r requirements.txt
python app.py
```

ブラウザで http://localhost:5000 を開く。
初回起動時、`admin` の初期パスワードがコンソールに表示される（控えておくこと）。

---

## 本番デプロイ（HTTPS 必須）

### 1. 環境変数を設定

```bash
export APP_ENV=production
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export SHIFT_DB_PATH=/var/lib/shift-flow/shift.db
export ADMIN_INIT_PASSWORD=（長いランダム文字列）

# Caddy / Nginx の後ろで動かす場合は追加
export TRUSTED_PROXY_HOPS=1
```

### 2. gunicorn で起動

```bash
gunicorn -w 1 -b 127.0.0.1:8000 app:app
```

> `app.run` や `python app.py` での本番起動は禁止。`APP_ENV=production` で例外停止する。
> worker を増やす場合は別途 Redis が必要（後述）。

### 3. HTTPS で公開

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
| `ADMIN_INIT_PASSWORD` | （ランダム生成） | 初回起動時の admin パスワード |
| `TRUSTED_PROXY_HOPS` | `0` | リバプロ段数。Caddy/Nginx 経由なら `1`、直接公開なら `0` |
| `RATELIMIT_STORAGE_URI` | `memory://` | worker 複数なら `redis://localhost:6379/0`（要 `pip install redis`） |

---

## バックアップ

WAL モード稼働中は **必ず** `sqlite3 .backup` を使う。`cp shift.db` は壊れたバックアップになる。

```bash
sqlite3 /var/lib/shift-flow/shift.db ".backup '/path/to/backup-$(date +%F).db'"
```

cron で日次実行を推奨。

### 復元

サービス停止 → 既存の `shift.db` / `shift.db-wal` / `shift.db-shm` を削除 → バックアップを `SHIFT_DB_PATH` の位置に配置 → サービス起動。

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

## トラブルシュート

| 症状 | 対処 |
|------|------|
| `SECRET_KEY が未設定です` で起動失敗 | `export SECRET_KEY=...` を設定 |
| admin の初期パスワードが分からない | 起動ログを確認。失った場合は上記「旧 DB から移行」と同じ手順 |
| ログインで 429 が返る | レート制限（1分10回）。1分待つ |
| `TRUSTED_PROXY_HOPS は非負整数...` で停止 | 値を `0` か `1` に修正 |
| `'redis' prerequisite not available` | `pip install redis` |
| 職員に「全体のシフト確認」が出ない | 仕様。フェーズ3 で確定シフトを実装後に開放予定 |
