# Shift-Flow

カウンセリングルームのシフト希望をスマホから集めて、管理者が確認・調整する Flask 製アプリ。
設計と安全対策の経緯は [CODE_REVIEW.md](CODE_REVIEW.md) を参照。

---

## 試用開始までの流れ（半日）

| 手順 | 内容 | 所要時間 |
|------|------|---------|
| 1. ローカルで動作確認 | `pip install` → `python3 app.py` で起動できることを確認 | 5 分 |
| 2. 本番サーバー準備 | 環境変数・DB フォルダ・gunicorn 起動・HTTPS 設定 | 30 分 |
| 3. 動作確認 + バックアップ復元演習 | 実機（PC・スマホ）でひととおり触る | 30 分 |
| 4. 関係者へ共有 | `/help` ページを職員に案内・ID を配布 | 5 分 |
| 5. 試用開始 | 3〜5 名で 1 か月運用 | — |

以下、各手順を順に説明します。

---

## 1. ローカルで動作確認（5 分）

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

ブラウザで http://localhost:5000 を開き、コンソールに表示された `admin` の初期パスワードでログインします。初回ログインは自動でパスワード変更画面に移動するので、新しいパスワードを設定してください（変更するまで他の画面には進めません）。

> Windows などで `python3` が無い場合は `python` でも動きます。

---

## 2. 本番サーバー準備（30 分）

### 2.1 環境変数を設定

```bash
export APP_ENV=production
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export SHIFT_DB_PATH=/var/lib/shift-flow/shift.db
export ADMIN_INIT_PASSWORD=（長いランダム文字列）
# Caddy / Nginx の後ろで動かす場合だけ
export TRUSTED_PROXY_HOPS=1
```

`ADMIN_INIT_PASSWORD` を渡しておけば、起動ログにパスワードが書かれなくなります。

### 2.2 DB 用フォルダを作る

```bash
sudo install -d -m 700 -o $(whoami) /var/lib/shift-flow
```

DB にはパスワードハッシュと備考が入るので、他ユーザーから読めない設定が必須です。

### 2.3 gunicorn で起動

```bash
gunicorn -w 1 -b 127.0.0.1:8000 app:app
# 起動後に 1 回だけ
chmod 600 /var/lib/shift-flow/shift.db*
```

> `-w 1` を推奨する理由：レート制限のカウンタが worker ごとに別になるため、`-w 4` だと 1 分 10 回制限が実質 1 分 40 回になります。worker を増やしたい場合は `RATELIMIT_STORAGE_URI=redis://...` を設定してください（別途 `pip install redis`）。
>
> `python3 app.py` での本番起動は `APP_ENV=production` で例外停止します。

### 2.4 HTTPS で公開

**Caddy の例**：
```caddyfile
shift.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

PaaS（Render / Railway / Fly.io）なら自動で HTTPS が付きます。

---

## 3. 動作確認 + バックアップ復元演習（30 分）

### 3.1 実機での目視チェック
PC とスマホでログイン → シフト入力 → 備考 → 送信完了の確認まで通しで触ってください。職員アカウントを 1 つ作り、その目線でも同じ流れを確認します。

### 3.2 バックアップ復元演習

```bash
# 1. バックアップ取得（WAL モードのため cp ではなく .backup を使う）
sqlite3 /var/lib/shift-flow/shift.db ".backup '/tmp/test.db'"

# 2. サービス停止 → 本物を退避 → バックアップを所定位置に
sudo systemctl stop shift-flow
mv /var/lib/shift-flow/shift.db* /tmp/keep/
cp /tmp/test.db /var/lib/shift-flow/shift.db

# 3. サービス起動 → ログイン確認 → 確認できたら本物を戻す
sudo systemctl start shift-flow
```

本番運用では cron で日次バックアップを取り、バックアップファイル自体も `chmod 600` で保護してください。

---

## 4. 関係者へ共有（5 分）

- ログイン後の `/help` ページを各職員に見てもらいます
- 管理者は新規ユーザー追加 → 一時パスワードを本人に渡す → 本人が初回ログインで再設定、という流れになります

---

## 5. 試用開始

社内 3〜5 名で 1 か月。毎週ログとバックアップを確認し、フィードバックを記録してください。

---

## リファレンス

### 環境変数一覧

| 変数 | 既定 | 説明 |
|------|------|------|
| `APP_ENV` | `development` | 本番は `production` |
| `SECRET_KEY` | — | セッション署名鍵。本番では必須 |
| `SHIFT_DB_PATH` | `instance/shift.db` | DB ファイルの場所。本番は絶対パス必須 |
| `ADMIN_INIT_PASSWORD` | ランダム生成 | 初回起動時の admin パスワード |
| `TRUSTED_PROXY_HOPS` | `0` | リバプロ段数。Caddy/Nginx 経由なら `1` |
| `RATELIMIT_STORAGE_URI` | `memory://` | 複数 worker なら `redis://...`（要 `pip install redis`） |

### トラブルシュート

| 症状 | 対処 |
|------|------|
| `SECRET_KEY が未設定です` で起動失敗 | `export SECRET_KEY=...` を設定 |
| admin の初期パスワードを失った | 下の「旧 DB から移行」手順で作り直す |
| ログイン時に 429 が返る | レート制限（1 分 10 回）。1 分待つ |
| `TRUSTED_PROXY_HOPS は非負整数...` で停止 | 値を `0` か `1` に修正 |
| `'redis' prerequisite not available` | `pip install redis` |
| 職員に「全体のシフト確認」が出ない | 仕様（フェーズ3 で開放予定） |
| パスワード変更画面から他画面に進めない | 強制変更中。新しいパスワードを設定すれば解除 |

### テストを動かす

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

### ユーザー完全削除（管理 CLI）

UI に削除ボタンは置いていません（誤操作による不可逆事故の防止）。退職や休職は「停止」で十分です。どうしても物理削除が必要な場合のみ：

```bash
sudo systemctl stop shift-flow
sqlite3 /var/lib/shift-flow/shift.db ".backup '/path/to/backup-pre-delete.db'"
sqlite3 /var/lib/shift-flow/shift.db \
  "DELETE FROM shifts WHERE name=(SELECT name FROM users WHERE username='対象ID'); \
   DELETE FROM users WHERE username='対象ID';"
sudo systemctl start shift-flow
```

### 旧 DB（Phase 1 以前）から移行

平文パスワードが残った旧 DB はそのままだとログイン不能です。admin を作り直してください：

```bash
cp shift.db shift.db.legacy.backup
sqlite3 shift.db "DELETE FROM users WHERE username='admin';"
export ADMIN_INIT_PASSWORD=（新しい長いランダム文字列）
# 起動 → admin でログイン → /manage_users から職員を再登録
```

シフト履歴は表示名で紐づくので、再登録時に旧と同じ表示名を使えば残ります。
