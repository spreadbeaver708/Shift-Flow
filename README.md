# Shift-Flow

職員がスマートフォンからシフト希望を提出し、管理者がまとめて確認・調整する小規模チーム向けアプリです。締め切り日になると職員は変更できなくなり、その内容がそのままシフトになります。

- 公開: クラウドサービス Render（Starterプラン）で運用中
- DB: SQLite + 永続ディスク
- 想定: 約10名
- 今後の予定: [docs/ROADMAP.md](docs/ROADMAP.md)（過去のレビュー・実装記録は [docs/archive/](docs/archive/)）
- 開発・AIエージェント向けの決まりごと: [CLAUDE.md](CLAUDE.md)

## 使い方

### 職員

1. IDとパスワードでログインする
2. 「シフト希望を入力」を開く
3. 日・月・木を「〇 出勤可」または「× 休み」にする
4. 必要な日だけ備考を追加して保存する
5. 締め切り日になると変更できなくなる（直したいときは管理者へ）

備考へ相談内容、健康情報、個人情報を書かないでください。

### 管理者

1. 「提出状況・締め切り」で締め切り日を決め、未提出者を確認する
2. 各スタッフの「編集」から希望を直接なおす（締め切り後も可）
3. 「みんなの希望を見る」で全員の予定をまとめて確認する
4. 月1回、操作ログとバックアップを確認する

職員の追加・修正・停止は「ユーザー管理」で行います。退職・休職時は削除せず停止します。パスワードを再発行しても本人のログイン中の端末はすぐにはログアウトされない（最大24時間）ため、すぐ使えなくするには「停止」を使います。

## 安全性

- パスワードはハッシュ化して保存
- パスワードは8〜128文字、頻出値とID一致を拒否（初回強制変更はなし・いつでも変更可）
- 無操作30分、ログイン後24時間で再認証
- ログイン試行はIP単位で制限。退職・紛失時は「停止」で締め出す
- 締め切り後の職員変更はサーバ側でも拒否（管理者のみ編集可）
- 管理操作は権限確認と監査ログを実施
- CSRF、CSP、入力サイズ制限、セキュリティCookieを適用
- ログアウトはCSRF保護されたPOST
- 氏名を含まない `/worker` を正規URLとして使用

## バックアップ

アプリは次のバックアップをSQLite Backup APIで作成し、毎回健全性を確認します。
作成中は一時ファイルを使い、完了後に置き換えるため、途中状態のファイルを正式バックアップとして残しません。

- スキーマ変更前: `pre-migration-*.db`
- 日次: `daily-YYYYMMDD.db` を14個保持（活動のあった日ごと。誰も使わない日はファイルが作られないため、必ずしも連続14日ではありません）
- 月次: `monthly-YYYYMM.db` を12個保持
- 手動: `manual-*.db`

保存先は `/var/data/backups/` です。同じディスクの故障には備えられないため、月1回、最新の月次バックアップを手元へ保存してください。

管理メニューの「バックアップ」で、最終保存日時・失敗の有無・外部保存の確認状況を画面で確認できます。月次バックアップを手元に保存したら「外部保存を確認した」を押すと記録され、しばらく記録が無いと警告が出ます。

Render のサービス画面「Shell」タブで、バックアップの一覧と健全性を確認できます:

```bash
ls -lt /var/data/backups/
sqlite3 /var/data/backups/<対象ファイル>.db "PRAGMA integrity_check;"
```

手元への保存は、サービス画面右上「Connect」→「SSH」に表示される接続先を使い、**自分のパソコン**から次を実行します（初回だけ、Render のアカウント設定に SSH 公開鍵の登録が必要です。Render の「SSH」ドキュメントの手順どおりに一度設定すれば以後は不要です）:

```bash
scp <SSH接続先>:/var/data/backups/monthly-YYYYMM.db ~/Downloads/
```

復元時はサービスを停止し、現在のDBとWALファイルを退避してから健全なバックアップを配置します。古い `shift.db-wal` と `shift.db-shm` は新DBへ適用しないでください。

### 復元リハーサル（本番に触れない練習）

いざという時に戻せることを、年1回以上、複製で練習しておきます。上の手順で `monthly-YYYYMM.db` を手元に保存したら、**自分のパソコン**でこのリポジトリのフォルダを開いて実行します（python3 が必要。「開発」の1行目まで済ませてあれば大丈夫です）:

```bash
sh scripts/restore_rehearsal.sh ~/Downloads/monthly-YYYYMM.db
```

スクリプトが複製を作り、健全性チェックと件数の確認まで自動で行います。続けて表示される案内に従って複製DBでアプリを起動し、画面で利用者・シフト希望・締め切り・操作ログが戻っていれば合格です（本番のデータには一切触れません）。

## Render で公開する

このアプリは Render の Blueprint（[render.yaml](render.yaml)）で公開しています。作り直すときの手順:

1. Render のアカウント（GitHub 連携済み）でログインし、「New +」→「Blueprint」→ このリポジトリを接続する（Webサービス・永続ディスク・HTTPSが自動で作られます）
2. 環境変数 `ADMIN_INIT_PASSWORD` だけ手で入力する（管理者の初期パスワード。8文字以上）
3. デプロイ後、ブラウザで `https://（アプリのURL）/readyz` を開き、`ready` と表示されることを確認する
4. ID `admin` と手順2で入力したパスワードでログインできることを確認する
5. 確認できたら `ADMIN_INIT_PASSWORD` を環境変数から削除する（以後は使いません）

## 毎月の確認

- [ ] `/logs` に不審なログイン失敗・権限エラーがない
- [ ] 管理メニューにバックアップ失敗警告がない
- [ ] 最新バックアップが新しく、`integrity_check` が `ok`
- [ ] 月次バックアップを手元へ保存した
- [ ] 本番の「今月」が日本時間と一致する
- [ ] `pip-audit -r requirements.txt` がクリーン

## 開発

```bash
python3 -m pip install -r requirements-dev.txt
python3 app.py
python3 -m pytest
python3 -m pip_audit -r requirements.txt
```

監視URL:

- `/healthz`: プロセスの生存確認
- `/readyz`: DBと必要テーブルを含む準備完了確認

主な環境変数:

| 変数 | 役割 |
|---|---|
| `APP_ENV` | `development` / `testing` / `production` |
| `SECRET_KEY` | 本番必須。Renderが生成 |
| `SHIFT_DB_PATH` | 本番必須。`/var/data/shift.db` |
| `ADMIN_INIT_PASSWORD` | 初回だけ必要。8文字以上。admin作成後は削除 |
| `TRUSTED_PROXY_HOPS` | Renderは `1` |
| `TRUST_CF_CONNECTING_IP` | Renderは `1`（全インバウンドがエッジ経由の前提）。デプロイ後に `/logs` のIPが実クライアントIPか確認し、不自然なら `0` |
| `SESSION_IDLE_MINUTES` | 無操作期限。既定30分 |
| `SESSION_ABSOLUTE_HOURS` | 総ログイン期限。既定24時間 |
| `LOGIN_RATE_LIMIT` | ログイン試行上限 |
| `RATELIMIT_STORAGE_URI` | レート制限の保存先。単一workerは `memory://` |
| `BACKUP_ON_STARTUP` | 自動バックアップのオン/オフ。既定: 本番はオン・開発はオフ |
| `BACKUP_KEEP` | 日次バックアップ保持数。既定14 |
| `MONTHLY_BACKUP_KEEP` | 月次バックアップ保持数。既定12 |
| `AUDIT_RETENTION` | 監査ログ保持件数。既定10000 |
| `TRUSTED_HOSTS` | 任意。設定するとHostヘッダを検証（不一致は400）。未設定なら無効。設定時は `/healthz`・`/readyz` も同じHostでのみ通るため、Renderの公開ホスト名を含める |

不正な設定値は安全な値へ黙って変更せず、修正方法を示して起動を停止します。

## 構成

- `app.py`: Flaskルートと画面処理（意図的に単一ファイル）
- `settings.py`: 環境変数の検証
- `storage.py`: DB初期化、移行、バックアップ、準備確認
- `security_utils.py`: パスフレーズ検証
- `time_utils.py`: UTC保存と日本時間表示
- `templates/`: 画面テンプレート（`base.html` が共通骨格）
- `static/style.css`: デザインとレスポンシブ表示
- `tests/`: 自動テスト
- `scripts/`: 運用の補助（復元リハーサル）
- `docs/`: 開発者向け文書 — [ROADMAP.md](docs/ROADMAP.md)（今後の予定）・[WORK_ORDERS.md](docs/WORK_ORDERS.md)（将来作業の指示書）・[archive/](docs/archive/)（過去の記録）
- `CLAUDE.md` / `AGENTS.md`: AIエージェント向けの決まりごと
- `.claude/skills/`: 開発用スキル（検証一式・月次点検）
