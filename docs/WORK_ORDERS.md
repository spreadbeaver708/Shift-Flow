# Shift-Flow 作業指示書（WORK ORDERS）

作成: 2026-07-10（Claude Fable 5）
対象読者: 将来この作業を実行する AI エージェント（Claude Opus / Codex 等）と開発者。
この文書だけで、元の設計意図を保ったまま各作業を完遂できるように書いてある。

## 使い方（必読）

1. **着手条件を満たしているか先に確認する**（[ROADMAP.md](ROADMAP.md) が正）。条件前の着手は禁止。
2. 各 WO は独立して実行できる。依存がある場合は明記してある。
3. **行番号は使っていない。アンカーは関数名・文字列**。必ず grep で現在地を確認してから編集する。
4. 「意図」を読んでから手を動かす。意図に反する“改善”をしない（例: パスワード定期変更の追加は NIST 違反。[../CLAUDE.md](../CLAUDE.md) の設計判断一覧を参照）。
5. 迷ったら**変更を小さくする**。このアプリの価値は「初心者が運用できる単純さ」にある。

## 共通プロトコル（全 WO 共通）

```bash
# 開始
git checkout main && git pull && git checkout -b sin
# 検証（全 WO の受け入れ基準に含まれる。/verify-release スキルでも実行可）
PYTHONWARNINGS=error python3 -m pytest -q -p no:cacheprovider   # 全件パス（2026-07時点 151）
python3 -m py_compile app.py settings.py storage.py security_utils.py time_utils.py
python3 -m pip check
git diff --check
# 依存を変更した WO のみ追加
python3 -m pip_audit -r requirements.txt
```

- 完了定義: 全テスト緑 ＋ README / アプリ内ヘルプ / [ROADMAP.md](ROADMAP.md) の関連記述が実装と一致 ＋ PR 作成（`sin` → `main`、本文に WO 番号を書く）。
- コミットは日本語で `type: 要約`。UI に触れた場合は実画面（モバイル375px）を確認する。
- 本番 DB・Render の本番環境には**コード作業中は一切触れない**。挙動確認はローカルの一時 DB で行う。
- スキーマを変える WO は、必ず「旧スキーマの DB を用意 → 移行 → 検証」のテストを含める（`ensure_ready` が移行前バックアップ `pre-migration-*.db` を自動作成することも確認する）。

---

<a id="wo-01"></a>
## WO-01: 旧URL `/confirm`・`/confirmed` の撤去

- **着手条件**: 2026-09-01 以降、かつ Render の HTTP ログ（ダッシュボード → Logs）で直近1ヶ月 `/confirm` `/confirmed` への実アクセスが無いこと。
  **注意**: アプリの操作ログ（/logs・audit_log）では確認**できない**。監査に残るのは職員が `/confirm` を踏んだときの 403（authz_fail）だけで、`/confirmed` と管理者・未ログインのアクセスは何も記録されないため、HTTP ログで見る。
- **意図**: 2026-06-24 の「確定シフト」廃止に伴う互換リダイレクト。誤遷移防止のために一時的に残しただけで、恒久機能ではない。撤去後にアクセスがあっても、既存の親切な 404 ページ（メニュー/ログインへの導線つき）に落ちるだけなのでリスクは小さい。
- **変更内容**:
  - `app.py`: 関数 `confirm_redirect` と `confirmed_redirect` を、直前の説明コメント（「旧「確定シフト」URL は廃止」「撤去予定: 2026-09」で grep）ごと削除。
  - `app.py`: ルート定義冒頭の「ルート定義（初心者向けの地図」コメントブロックから `互換:   /confirm  /confirmed` の行を削除。
  - `tests/test_deadline.py`: `test_legacy_confirm_redirects` と `test_legacy_confirmed_redirects` を削除（セクション見出し「旧URLの互換リダイレクト」ごと）。
  - `tests/test_integration_2026_06_25.py` の `test_flash_wording_pins`: `/confirm` に対するアサーション2行（`body2 = admin_client.get("/confirm", ...)` と直後の `assert`）**だけ**を削除し、`/staff/nonexistent` の検証は残す（テスト関数自体は削除しない）。
  - 仕上げに `grep -rn "confirm" app.py templates/ tests/ README.md docs/ROADMAP.md` を実行し、取り残しが無いことを確認（`confirmed_shifts`（DB表・WO-02 対象）への言及は残ってよい）。
  - [ROADMAP.md](ROADMAP.md) の「予定された作業」からこの項目を消す。
- **受け入れ基準**: テスト 149 件全パス（151−2）。`/confirm` への GET が 404 を返す（テストクライアントで確認してよい）。
- **やらないこと**: 404 の代わりに新しいリダイレクトを張らない（互換の再導入になる）。
- **ロールバック**: コミットを revert するだけ（DB 変更なし）。

---

<a id="wo-02"></a>
## WO-02: スキーマ掃除 — `must_change_password` 列と `confirmed_shifts` 表の削除

- **着手条件**: 本番 DB が SCHEMA_VERSION 31 で安定稼働し、v30 以前へ戻す可能性が無いと運用者が判断したとき（目安 2026-10 以降）。直近の外部バックアップが存在すること。
- **意図**: どちらも旧仕様（初回強制変更／確定シフト2段階）の名残で、コードはもう参照していない。移行安全のため「非破壊で温存」してきたが、ロールバック不要が確定したら消してよい。**削除は必ずスキーマ移行として行い**、`ensure_ready` の自動 pre-migration バックアップに乗せる。
- **前提知識**:
  - `storage.py` の `SCHEMA_VERSION`（現在 31）と `_initialize_schema(previous_version=...)` が移行の仕組み。`ensure_ready` が「既存 DB かつ旧バージョン」のとき pre-migration バックアップを自動作成する。
  - SQLite の `ALTER TABLE ... DROP COLUMN` は 3.35 以降で使用可（Python 3.14 同梱の sqlite3 は対応済み）。
- **変更内容**（すべて `storage.py`）:
  1. `SCHEMA_VERSION = 31` → `32`。
  2. `_initialize_schema` 内の must_change_password ブロックを削除:
     - `PRAGMA table_info(users)` で列を**追加**している分岐（`ALTER TABLE users ADD COLUMN must_change_password` で grep）
     - `UPDATE users SET must_change_password=0` の一括ゼロ化
  3. 代わりに移行処理を追加（分岐は `previous_version < 32` でも、既存コードの `previous_version < SCHEMA_VERSION` パターンでもよい。**列・表の存在確認をしてから消す**のが本質で、それにより冪等になる）:
     ```python
     user_columns = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
     if "must_change_password" in user_columns:
         conn.execute("ALTER TABLE users DROP COLUMN must_change_password")
     conn.execute("DROP TABLE IF EXISTS confirmed_shifts")
     ```
     ※ 列の存在確認をしてから DROP すること（v0 からの新規作成 DB には列が最初から無いため）。
  4. admin 初期作成の INSERT 文から `must_change_password` 列と対応する値を外す（`INSERT OR IGNORE INTO users` で grep）。
  5. 「確定シフト（confirmed_shifts）は廃止。既存DBのテーブルは非破壊で温存」というコメントを現状に合わせて書き換え。
- **テスト**:
  - `tests/test_db.py`: must_change_password を参照する既存テストを「移行後は列が存在しない」ことの検証へ書き換える。旧スキーマ（列あり・confirmed_shifts あり・user_version=31）の DB をテスト内で組み立て → `ensure_ready` → 列と表が消えていること、`pre-migration-v31-to-v32-*.db` が作られることを確認するテストを追加。
  - `tests/conftest.py` の「must_change_password 列は互換のため残る」というコメントを更新。
- **受け入れ基準**: 全テスト緑。新規作成 DB・v31 からの移行 DB の両方で `PRAGMA table_info(users)` に列が無く、`sqlite_master` に confirmed_shifts が無い。
- **やらないこと**: users 表の再作成（CREATE→コピー→リネーム）はしない。DROP COLUMN で足りる。
- **ロールバック**: コードを revert し、DB は自動作成された `pre-migration-v31-to-v32-*.db` から戻す（README「バックアップ」の復元手順）。

---

<a id="wo-03"></a>
## WO-03: レート制限ストレージを Redis へ移行

- **着手条件**: gunicorn の worker 数を 2 以上へ増やす**前**（必須の前提作業）。単一 worker のままなら着手しない。
- **意図**: 現在の `memory://` は「単一 worker・再起動でカウンタ消失を許容」という前提で正しい。worker を増やすと各プロセスが別カウンタを持ち、ログインレート制限が黙って弱体化するため、その前に共有ストアへ移す。
- **変更内容**:
  1. Render で Key Value（Redis 互換）インスタンスを作成し、内部接続 URL を得る。
  2. `requirements.txt`: コメントアウトされている redis の行（`# redis==` で grep）を有効化。**バージョンはその時点の安定版に更新し、`pip-audit` を通すこと**（2026-07 時点の記載値をそのまま使わない）。
  3. `render.yaml` の envVars に `RATELIMIT_STORAGE_URI`（値は Render の内部 URL。`sync: false` で手入力にするのが安全）を追加。
  4. **アプリコードの変更は不要**（`settings.py` が `RATELIMIT_STORAGE_URI` を既に読み、`app.py` の Limiter に渡している）。README の環境変数表の該当行を現状に合わせて更新。
- **受け入れ基準**: デプロイ後、`/login` へ連続 POST で 429 が返ること（LOGIN_RATE_LIMIT を一時的に小さくした検証用の別サービスで確認するのが安全）。アプリ再起動後もカウンタが維持されること。
- **やらないこと**: 単一 worker のまま Redis を導入しない（障害点と運用対象が増えるだけ）。
- **ロールバック**: env の `RATELIMIT_STORAGE_URI` を削除（既定 `memory://` に戻る）。

---

<a id="wo-04"></a>
## WO-04: session_epoch — パスワード再発行・停止で全端末を即ログアウト

- **着手条件**: 「パスワード再発行・停止後も他端末の旧セッションが最大24時間有効」という現行の受容（運用は『停止』ボタンで代替）が許容できなくなったとき。例: 機微情報を扱い始める、実際の乗っ取り・退職トラブルが起きた。
- **意図**: セッション Cookie は `username` しか持たず、サーバは毎リクエスト DB からロールと有効状態を再取得する設計（停止は即反映される）。ここに「世代番号」を足し、番号が変わったセッションを無効化する。**約15行の最小実装**であり、セッションストアの導入など大掛かりな変更はしない。
- **依存**: スキーマ変更を伴うため、WO-02 が未実施なら**同時に実施**して移行を1回にまとめるのが望ましい。
- **変更内容**:
  1. `storage.py`: `SCHEMA_VERSION` を +1。`_initialize_schema` の users CREATE 文と移行分岐に `session_epoch INTEGER NOT NULL DEFAULT 0` を追加（`ALTER TABLE users ADD COLUMN`、既存行は DEFAULT 0 のままでよい）。
  2. `app.py` `login()`: 認証成功時の SELECT に `session_epoch` を含め、`session["epoch"] = <その値>` を保存（`session["authenticated_at"]` を設定している箇所の隣）。
  3. `app.py` `load_current_user()`: ユーザー行の SELECT に `session_epoch` を含め、`session.get("epoch") != row の epoch` なら `session.clear()` + 既存文言「安全のためログアウトしました。もう一度ログインしてください。」で flash して return（絶対期限切れの分岐と同じ形）。**epoch 未保持の旧セッションは不一致扱いで再ログインさせる**（1回だけの不便を許容。黙って通す分岐を作らない）。
  4. epoch のインクリメント（`UPDATE users SET session_epoch = session_epoch + 1 WHERE username=?`）を次の3箇所に追加:
     - `change_password()` 本人変更の UPDATE 直後（現行の `session.clear()` は残す）
     - `manage_users()` 管理者がパスワードを設定する分岐（監査 `admin_password_set` を記録している箇所）
     - `manage_users()` の `action == "toggle"` で **停止（1→0）にする**とき（復活時は不要）。
       停止中は `load_current_user` が毎回セッションを破棄するので一見冗長だが、**復活（0→1）した瞬間に停止前の旧セッションが生き返るのを防ぐ**ために必要。
  5. **文言の連動更新（重要）**: 「最大24時間」で grep し、README・`templates/manage_users.html` の説明文を「新しいパスワードを設定すると、ログイン中の端末は次の操作でログアウトされます」等へ更新。この文言を検証しているテストがあれば同時に更新する。
- **テスト**: ①本人がパスワード変更 → 別クライアントの旧セッションが次のリクエストでログイン画面へ ②管理者が再設定 → 同様 ③**停止 → 復活の後**、停止前の旧セッションが再ログインを要求される（epoch がやることの証明。既存の「停止中は弾かれる」テストとはここが違う）④epoch を持たない旧形式セッションが安全側でログアウトされる。
- **受け入れ基準**: 全テスト緑。上記4シナリオが自動テストで固定されている。**「最大24時間」が grep で0件**（README・templates）。※セッション総期限の説明にある「24時間」（`SESSION_ABSOLUTE_HOURS`・README「無操作30分、ログイン後24時間で再認証」・render.yaml のコメント）は本 WO と無関係の正しい記述なので**消さない**。
- **やらないこと**: サーバサイドセッションストア（Redis セッション等）への移行。Cookie 設計の変更。
- **ロールバック**: コード revert。列は残っても無害（参照が無くなるだけ）。

---

<a id="wo-05"></a>
## WO-05: アカウント単位のログイン失敗スロットル

- **着手条件**: `/logs` で特定 ID へのログイン失敗の集中が観測されたとき、または機微情報を扱う運用へ変わるとき。
- **意図**: 現行の防御は「IP 単位 20回/分 ＋ 弱いパスワード拒否 ＋ 応答時間の平準化」。IP 分散攻撃には ID 単位の制御が効く。**新しいテーブルや外部ストアは足さず、既存の audit_log（login_fail が actor=試行ID で残っている）を集計に使う**。再起動してもカウントが消えない利点もある。
- **変更内容**（`app.py` `login()` の POST 分岐）:
  1. ユーザー照会の前に、直近10分の失敗回数を取得:
     `SELECT COUNT(*) FROM audit_log WHERE action='login_fail' AND actor=? AND ts >= ?`
     （ts は UTC ISO 文字列で同一書式のため文字列比較で範囲指定できる。閾値・窓は定数 `LOGIN_FAIL_LOCK_THRESHOLD = 10` / `LOGIN_FAIL_WINDOW_MINUTES = 10` としてファイル上部の検証ヘルパー付近に置く）
  2. 閾値以上なら: ダミーハッシュ検証（既存 `_DUMMY_PW_HASH`）で応答時間を保ち、`login_fail` を通常どおり監査記録し、**既存と同一の文言**「IDまたはパスワードが正しくありません」を返す。ID の存在有無・ロック中であることを応答から判別できないようにする（列挙対策。専用メッセージを作らない）。
  3. 成功時は何もしない（窓が過ぎれば自然に解除。解除処理・管理画面は作らない）。
  - 補足: audit_log の actor は保存時に 64 字へ切り詰められるが、実在ユーザーIDは最大 32 字（USERNAME_RE）なので集計に影響しない。ID 未入力の失敗は actor='anonymous' に集約される（まとめてスロットルされても実害なし）。
- **テスト**: ①10回失敗後は正しいパスワードでも一時的に入れない ②10分経過（`now_utc` を monkeypatch）で入れる ③文言が通常失敗と同一 ④正規ユーザーの成功ログインは影響を受けない。
- **受け入れ基準**: 全テスト緑。既存のレート制限テスト・タイミング平準化の仕組みを壊していない。
- **やらないこと**: アカウントの恒久ロック（管理者の解除作業が生まれ、10名運用の負担になる）。CAPTCHA。ロック専用のエラーメッセージ。
- **ロールバック**: コード revert のみ（スキーマ変更なし）。

---

<a id="wo-06"></a>
## WO-06: 性能 — shifts 索引と監査ログ削除頻度（測ってから）

- **着手条件**: 体感の遅延が報告される、または利用者が数十名規模へ増えたとき。**必ず先に計測**（どの画面が遅いか）。
- **意図**: 10名規模では全表走査でも問題ないため意図的に未実装。やる場合も最小で。
- **変更内容（候補）**:
  - `storage.py` `_initialize_schema` に `CREATE INDEX IF NOT EXISTS idx_shifts_ym_user ON shifts(year, month, username)` を追加（冪等なのでバージョン bump 不要）。
  - `app.py` `log_action` 内の保持上限 DELETE（毎回実行）を、呼び出し N 回に1回へ間引く場合は、単純な確率や id 剰余ではなく「INSERT 後の`id % 100 == 0` のときだけ実行」など決定的な方法にする。
- **受け入れ基準**: 全テスト緑。計測値の改善をPRに記録。
- **やらないこと**: キャッシュ層・非同期化の導入。

---

<a id="wo-07"></a>
## WO-07: Blueprint 分割（最後の手段）

- **着手条件**: `app.py` の変更が**実際に**困難になったとき（行数ではなく、変更のたびに事故が起きる・見通せない、という体感で判断）。
- **意図**: 単一ファイルは**意図的な設計**（初心者が上から下まで追える）。歴代レビューで繰り返し「分割しない」と判断してきた。分割は可読性の改善ではなく、変更困難の解消としてだけ行う。
- **変更内容（分割する場合の指針）**: `auth`（login/logout/change_password）／`shifts`（index/worker/staff_edit/handle_input）／`admin`（admin/submissions/deadline/manage_users/logs）／`ops`（healthz/readyz/backup_check/help）の4分割まで。共通ヘルパー（client_ip, log_action, resolve_ym 系, deadline 系）は1つの helpers モジュールへ。**テンプレート・テスト・URL は一切変えない**（挙動不変のリファクタリング）。1 PR で完結させ、既存テストを一切書き換えずに全緑にする。
- **受け入れ基準**: 既存テストが**無修正**で全緑（これが挙動不変の証明）。
- **やらないこと**: URL 変更、テンプレ再配置、分割ついでの“改善”。

---

<a id="wo-08"></a>
## WO-08: TRUSTED_HOSTS の有効化（任意の防御強化）

- **着手条件**: いつでも可。運用者が Render の実ホスト名を把握していること。
- **意図**: Host ヘッダ検証はコード実装済み・**既定で無効**（未設定なら検証しない）。無効が既定なのは、誤設定でヘルスチェックごと締め出す事故を防ぐ安全側の判断。有効化はセキュリティの底上げだが必須ではない。
- **手順**:
  1. 本番の公開ホスト名を確認（例: `shift-flow.onrender.com`。カスタムドメインがあれば併記）。
  2. `render.yaml` のコメントアウトされた `TRUSTED_HOSTS` を有効化し、**Render のヘルスチェックが到達するホスト名を必ず含める**（含めないと `/healthz`・`/readyz` が 400 になりデプロイが unhealthy 判定される）。
  3. デプロイ → `/readyz` が 200 で healthy を確認 → `curl -H "Host: evil.example" https://<実ホスト>/login` が 400 系になることを確認。
- **ロールバック**: env から TRUSTED_HOSTS を削除（検証オフに戻る）。

---

## 付記: 運用作業（コード変更なし）

復元リハーサル・実端末ウォークスルー・月次点検は [ROADMAP.md](ROADMAP.md) と README が正。エージェントが手伝う場合は `scripts/restore_rehearsal.sh` と `/monthly-check` スキルを使う。
