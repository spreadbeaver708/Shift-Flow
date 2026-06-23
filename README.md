# Shift-Flow

職員がスマートフォンからシフト希望を提出し、管理者が確認・確定する小規模チーム向けアプリです。

- 公開: Render Starter
- DB: SQLite + 永続ディスク
- 想定: 約10名
- 詳細な検証結果: [CODE_REVIEW.md](CODE_REVIEW.md)
- 今後の改善: [IMPROVEMENTS.md](IMPROVEMENTS.md)

## 使い方

### 職員

1. IDと一時パスワードでログインする
2. 15文字以上のパスフレーズへ変更する
3. 「自分のシフト希望を入力」を開く
4. 日・月・木を「〇 出勤可」または「× 休み」にする
5. 必要な日だけ備考を追加して保存する
6. 「確定シフトを見る」で決定内容を確認する

備考へ相談内容、健康情報、個人情報を書かないでください。

### 管理者

1. 「提出状況を見る」で未提出者を確認する
2. 「希望シフトを見る」で希望と備考を確認する
3. 「確定シフトを作る」で出勤日を決める
4. 月1回、操作ログとバックアップを確認する

職員の追加・修正・停止は「ユーザー管理」で行います。退職・休職時は削除せず停止します。

## 安全性

- パスワードはハッシュ化して保存
- 新規パスワードは15〜128文字、頻出値とID一致を拒否
- 初回ログインと管理者再設定後は本人の変更を強制
- 無操作30分、ログイン後24時間で再認証
- 管理操作は権限確認と監査ログを実施
- CSRF、CSP、入力サイズ制限、セキュリティCookieを適用
- ログアウトはCSRF保護されたPOST
- 氏名を含まない `/worker` を正規URLとして使用

## バックアップ

アプリは次のバックアップをSQLite Backup APIで作成し、毎回健全性を確認します。
作成中は一時ファイルを使い、完了後に置き換えるため、途中状態のファイルを正式バックアップとして残しません。

- スキーマ変更前: `pre-migration-*.db`
- 日次: `daily-YYYYMMDD.db` を14個保持
- 月次: `monthly-YYYYMM.db` を12個保持
- 手動: `manual-*.db`

保存先は `/var/data/backups/` です。同じディスクの故障には備えられないため、月1回、最新の月次バックアップを手元へ保存してください。

```bash
ls -lt /var/data/backups/
sqlite3 /var/data/backups/<対象ファイル>.db "PRAGMA integrity_check;"
```

復元時はサービスを停止し、現在のDBとWALファイルを退避してから健全なバックアップを配置します。古い `shift.db-wal` と `shift.db-shm` は新DBへ適用しないでください。

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
| `ADMIN_INIT_PASSWORD` | 初回だけ必要。15文字以上。admin作成後は削除 |
| `TRUSTED_PROXY_HOPS` | Renderは `1` |
| `TRUST_CF_CONNECTING_IP` | Renderは `1` |
| `SESSION_IDLE_MINUTES` | 無操作期限。既定30分 |
| `SESSION_ABSOLUTE_HOURS` | 総ログイン期限。既定24時間 |
| `LOGIN_RATE_LIMIT` | ログイン試行上限 |
| `RATELIMIT_STORAGE_URI` | レート制限の保存先。単一workerは `memory://` |
| `BACKUP_KEEP` | 日次バックアップ保持数。既定14 |
| `MONTHLY_BACKUP_KEEP` | 月次バックアップ保持数。既定12 |
| `AUDIT_RETENTION` | 監査ログ保持件数。既定10000 |

不正な設定値は安全な値へ黙って変更せず、修正方法を示して起動を停止します。

## 構成

- `app.py`: Flaskルートと画面処理
- `settings.py`: 環境変数の検証
- `storage.py`: DB初期化、移行、バックアップ、準備確認
- `security_utils.py`: パスフレーズ検証
- `time_utils.py`: UTC保存と日本時間表示
- `templates/base.html`: 全画面の共通骨格
- `static/style.css`: デザインとレスポンシブ表示
