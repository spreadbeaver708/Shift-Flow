# Shift-Flow（カウンセリングルーム シフト管理アプリ）

スタッフがスマホからシフト希望を入力し、管理者が集計・調整できる Flask 製アプリ。

- 設計・セキュリティの背景は [CODE_REVIEW.md](CODE_REVIEW.md) を参照。
- 本書はフェーズ1（試用開始の前提）終了時点での動かし方をまとめたもの。

---

## 必須環境変数

| 変数 | 必須 | 用途 |
|------|------|------|
| `SECRET_KEY` | **本番では必須**（未設定だと起動失敗） | セッション署名鍵 |
| `APP_ENV` | 本番では `production` | Cookie の Secure 属性切替、debug 起動防止 |
| `SHIFT_DB_PATH` | **本番では絶対パス必須**（相対パスを指定すると起動失敗） | `shift.db` の置き場（未指定なら `instance/shift.db`） |
| `ADMIN_INIT_PASSWORD` | 初回起動時のみ参照 | `admin` ユーザーの初期パスワード（未設定ならランダム生成しログに一度だけ表示） |
| `RATELIMIT_STORAGE_URI` | 推奨（複数 worker 運用時） | レート制限の保管先（例: `redis://localhost:6379/0`）。未設定時は `memory://`、worker ごとに別カウンタになる。`redis://` を指定する場合は別途 `pip install redis` が必要 |

`SECRET_KEY` は十分長いランダム文字列を使う：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## ローカル開発

```bash
pip install -r requirements.txt
flask --app app run            # debug は無効。APP_ENV 未設定で動く
# もしくは
python app.py
```

- `SECRET_KEY` 未設定でも開発時はランダム生成にフォールバックする。
- `instance/shift.db` が自動生成される。初回は `admin` のパスワードがコンソールに出力される。

---

## 本番デプロイ（HTTPS）

**HTTPS 必須**。Cookie の `Secure` 属性は `APP_ENV=production` のときだけ有効になるため、平文 HTTP では運用しない。

### 環境変数の例

```bash
export APP_ENV=production
export SECRET_KEY="（python -c "import secrets; print(secrets.token_hex(32))" の結果）"
export SHIFT_DB_PATH=/var/lib/shift-flow/shift.db
export ADMIN_INIT_PASSWORD="（初回のみ・十分長いランダム値）"
```

### gunicorn での起動

試用初期（小規模）：

```bash
gunicorn -w 1 -b 127.0.0.1:8000 app:app
```

複数 worker で運用する場合は **レート制限のための共有ストレージを指定**（推奨）：

```bash
# Redis ストレージを使う場合は redis パッケージを別途インストール
# （requirements.txt にはコメントアウトされた redis==5.0.8 のヒントがある）
pip install redis==5.0.8

export RATELIMIT_STORAGE_URI=redis://127.0.0.1:6379/0
gunicorn -w 2 -b 127.0.0.1:8000 app:app
```

> ⚠️ `redis://` 系を指定した状態で `redis` パッケージが入っていないと、リクエスト時に
> `limits.errors.ConfigurationError: 'redis' prerequisite not available` で落ちます。
> 試用初期はそのまま `memory://`（既定）＋ `-w 1` で運用するのが安全です。

- `app.run(debug=True)` は **使用禁止**（CODE_REVIEW.md §3 G）。
- `python app.py` は `APP_ENV=production` のとき例外で停止する。
- gunicorn は `SHIFT_DB_PATH` を **絶対パス** で指定する。本番では相対パス指定で起動失敗する（CODE_REVIEW.md §3 S）。
- 初回起動の admin 作成は `INSERT OR IGNORE` で冪等化されており、worker 数によらず1度だけ書き込まれる。ランダム初期パスワードのログ表示も書き込みに成功した worker 1 つだけが出力する。
- レート制限の `memory://`（既定）は worker ごとに別カウンタになるため、複数 worker 運用ではレートが実質ゆるむ。`-w 1` で運用するか、`RATELIMIT_STORAGE_URI` に Redis を指定すること。

### HTTPS の終端

以下のいずれかで HTTPS を終端する：

1. **PaaS（Render / Railway / Fly.io など）の自動 HTTPS** を利用。
2. **Nginx / Caddy などのリバースプロキシ＋ Let's Encrypt**。
   - Caddy 例：
     ```caddyfile
     shift.example.com {
         reverse_proxy 127.0.0.1:8000
     }
     ```
   - Nginx の場合は `proxy_set_header X-Forwarded-Proto https;` を必ず設定する。

### 受け入れチェック（公開前）

CODE_REVIEW.md §8 を上から順に実機確認すること。最低限：

- `SECRET_KEY` を未設定にすると本番起動が失敗する。
- 平文 HTTP では Cookie が送られない（Secure 属性が効いている）。
- 職員アカウントで `/admin` `/manage_users` が 403/302 になる。
- 停止した職員の旧セッションで `/menu` `/worker` にアクセスできない。
- 連続ログイン失敗で 429 が返る。

---

## バックアップ

`SHIFT_DB_PATH` で指定したファイルを日次でコピーする。例：

```bash
cp /var/lib/shift-flow/shift.db /var/backups/shift-flow/shift-$(date +%F).db
```

復元時はサービス停止 → ファイル差し替え → サービス起動。

---

## トラブルシュート

- **「`SECRET_KEY` が未設定です（本番では必須）」で起動失敗** → 環境変数 `SECRET_KEY` を設定。
- **admin の初期パスワードが分からない** → `ADMIN_INIT_PASSWORD` を指定して **新規 instance** で起動するか、起動ログを確認（ランダム生成時のみ表示）。
- **ログインが何度やっても失敗する** → `/login` は 1 分 10 回でレート制限。1 分待つ。
