# Shift-Flow

カウンセリングルームのシフト希望をスマホから集めて、管理者が確認・調整する Flask 製アプリ。
設計と安全対策の経緯は [CODE_REVIEW.md](CODE_REVIEW.md) を参照。

---

## 試用開始までの流れ（半日）

| 手順 | 内容 | 所要時間 |
|------|------|---------|
| 1. ローカルで動作確認 | 自分の PC で起動できることを確認 | 5 分 |
| 2. Render で公開 | GitHub とつないでインターネットに公開（推奨） | 30 分 |
| 3. 動作確認 | PC・スマホで触る／データが消えないか確認 | 30 分 |
| 4. 関係者へ共有 | `/help` ページを職員に案内・ID を配布 | 5 分 |
| 5. 試用開始 | 3〜5 名で 1 か月運用 | — |

以下、各手順を順番に説明します。サーバーとデータベースをこの構成にした理由は、末尾の「付録 B」にまとめてあります。

---

## 1. ローカルで動作確認（5 分）

まず自分の PC で動くことを確認します。

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

ブラウザで http://localhost:5000 を開き、コンソールに表示された `admin` の初期パスワードでログインします。初回ログインは自動でパスワード変更画面に移動するので、新しいパスワードを設定してください（変更するまで他の画面には進めません）。

> Windows などで `python3` が無い場合は `python` でも動きます。

---

## 2. Render で公開する（推奨・30 分）

**Render** は、GitHub に置いたアプリをインターネットに公開してくれるサービスです。HTTPS 化や常時起動といった面倒なサーバー設定を自動でやってくれるので、初心者でも安全に公開できます。

このアプリには `render.yaml` という設定ファイルが入っていて、**公開に必要な設定をほぼ自動で行います**。あなたが手を動かすのは「ボタンを押す」のと「パスワードを 1 つ入力する」だけです。

### 事前に用意するもの

- **GitHub アカウント** … このアプリのコードを置く場所
- **Render アカウント** … https://render.com で無料登録（公開そのものは有料プランを使います／料金は後述）

### ステップ 1：コードを GitHub に置く

このアプリ一式を、自分の GitHub リポジトリに push しておきます（すでにある場合はそのままで大丈夫です）。

### ステップ 2：Render に読み込ませる

1. Render にログインし、右上の **「New +」→「Blueprint」** を選びます。
2. このアプリの GitHub リポジトリを選んで接続します。
3. Render が自動で `render.yaml` を見つけ、サーバー・データの保存場所・HTTPS などの設定を読み込みます。

### ステップ 3：管理者パスワードだけ入力する

読み込み後、`ADMIN_INIT_PASSWORD`（管理者の初期パスワード）の入力を求められます。
**長めのランダムな文字列**を決めて入力してください（例：パスワード生成ツールで 20 文字以上）。

> これは最初の 1 回だけ使うパスワードです。あとで管理者でログインしたときに、自分の好きなパスワードへ変更します。
> 暗号鍵（`SECRET_KEY`）などほかの設定は Render が自動で安全な値を作るので、入力は不要です。

### ステップ 4：公開する

**「Apply」**（または「Create」）を押すと、Render がアプリを起動します。数分待つと
`https://shift-flow-xxxx.onrender.com` のような URL が発行され、これがそのまま公開アドレスになります（HTTPS 付き）。

これで公開は完了です。次の「3. 動作確認」へ進んでください。

### 料金の目安

| 項目 | 金額 |
|------|------|
| Render Starter プラン（サーバー） | $7 / 月 |
| 永続ディスク 1GB（データ保存） | $0.25 / 月 |
| HTTPS・`onrender.com` のアドレス | 無料 |
| **合計** | **約 $7.25 / 月（およそ ¥1,100）** |

> データを消さずに保存するには有料プランが必要です。無料プランは「15 分使わないと停止する」「保存したデータが消える」ため、本番には使えません。

> **データの保存場所**：このアプリのデータベースは `/var/data` という「消えない場所（永続ディスク）」に保存されます。Render の通常の保存場所は再公開のたびに消えますが、この設定のおかげで**シフトやユーザー情報は再公開しても残ります**。

---

## 3. 動作確認（30 分）

### 3.1 実機で触ってみる

PC とスマホでログイン → シフト入力 → 備考 → 送信完了まで、ひととおり触ってください。
さらに職員アカウントを 1 つ作り、その職員でログインして、

- 同じ流れでシフトを入力できること
- 管理者用ページ（`/admin`）を**開けない**こと（「403」と表示されれば正常）

も確認します。

### 3.2 データが消えないか確認（いちばん大事）

Render の画面でアプリを一度 **「Manual Deploy」→「Redeploy」** して再起動し、さきほど作ったユーザーやシフトが**そのまま残っている**ことを確認します。
残っていれば、データが正しく「消えない場所」に保存できています。

### 3.3 バックアップを確認しておく

- Render は **1 日 1 回**、自動でデータのバックアップ（スナップショット）を取り、**7 日間**保管します。サービス画面の **「Disks」** から確認できます。
- 手元にもコピーを残したいときは、Render の **「Shell」** タブで次を実行してファイルを作り、ダウンロードします（やや上級・任意）：

  ```bash
  sqlite3 /var/data/shift.db ".backup '/tmp/backup.db'"
  ```

  （WAL モードのため `cp` ではなく `.backup` を使います。）
- 試用期間中は、週に 1 回この確認をしておくと安心です。

> **大切な注意（相談室のため）**：備考欄には、相談内容や個人を特定できる情報は書かないよう職員に伝えてください。保存データと自動バックアップは暗号化されますが、そもそも機微な情報を入れない運用がいちばん安全です。

---

## 4. 関係者へ共有（5 分）

- ログイン後の `/help` ページを各職員に見てもらいます。
- 管理者は「新規ユーザー追加 → 一時パスワードを本人に渡す → 本人が初回ログインで再設定」という流れで職員を登録します。

---

## 5. 試用開始

社内 3〜5 名で 1 か月。毎週、ログとバックアップを確認し、フィードバックを記録してください。

---

## リファレンス

### 環境変数一覧

Render で公開する場合、これらは `render.yaml` が自動で設定します（手入力するのは `ADMIN_INIT_PASSWORD` だけ）。自分のサーバーで動かす場合は付録 A を参照してください。

| 変数 | 既定 | 説明 |
|------|------|------|
| `APP_ENV` | `development` | 本番は `production` |
| `SECRET_KEY` | — | セッション署名鍵。本番では必須（Render は自動生成） |
| `SHIFT_DB_PATH` | `instance/shift.db` | DB ファイルの場所。本番は絶対パス必須（Render は `/var/data/shift.db`） |
| `ADMIN_INIT_PASSWORD` | ランダム生成 | 初回起動時の admin パスワード |
| `TRUSTED_PROXY_HOPS` | `0` | リバプロ段数。Render / Caddy / Nginx 経由なら `1` |
| `RATELIMIT_STORAGE_URI` | `memory://` | 複数 worker なら `redis://...`（要 `pip install redis`） |

### トラブルシュート

| 症状 | 対処 |
|------|------|
| `SECRET_KEY が未設定です` で起動失敗 | `SECRET_KEY` を設定（Render は自動生成されるので通常は不要） |
| データやユーザーが消えた／admin に戻った | `SHIFT_DB_PATH=/var/data/shift.db` とディスクのマウント先 `/var/data` が一致しているか確認 |
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

> **Render の場合**：`sudo systemctl stop/start shift-flow` の代わりに、Render 画面でサービスを **Suspend → Resume** し、`sqlite3` コマンドは **「Shell」タブ**で実行します。DB のパスは `/var/data/shift.db` です。

### 旧 DB（Phase 1 以前）から移行

平文パスワードが残った旧 DB はそのままだとログイン不能です。admin を作り直してください：

```bash
cp shift.db shift.db.legacy.backup
sqlite3 shift.db "DELETE FROM users WHERE username='admin';"
export ADMIN_INIT_PASSWORD=（新しい長いランダム文字列）
# 起動 → admin でログイン → /manage_users から職員を再登録
```

シフト履歴は表示名で紐づくので、再登録時に旧と同じ表示名を使えば残ります。

---

## 付録 A：自分のサーバー（VPS）で公開する場合（上級者向け）

Render を使わず、自前の Linux サーバー（VPS）で動かす場合の手順です。`sudo` や `systemctl` の知識が必要なので、不安な場合は本文の「2. Render で公開する」をおすすめします。

### A.1 環境変数を設定

```bash
export APP_ENV=production
export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export SHIFT_DB_PATH=/var/lib/shift-flow/shift.db
export ADMIN_INIT_PASSWORD=（長いランダム文字列）
# Caddy / Nginx の後ろで動かす場合だけ
export TRUSTED_PROXY_HOPS=1
```

`ADMIN_INIT_PASSWORD` を渡しておけば、起動ログにパスワードが書かれなくなります。

### A.2 DB 用フォルダを作る

```bash
sudo install -d -m 700 -o $(whoami) /var/lib/shift-flow
```

DB にはパスワードハッシュと備考が入るので、他ユーザーから読めない設定が必須です。

### A.3 gunicorn で起動

```bash
gunicorn -w 1 -b 127.0.0.1:8000 app:app
# 起動後に 1 回だけ
chmod 600 /var/lib/shift-flow/shift.db*
```

> `-w 1` を推奨する理由：レート制限のカウンタが worker ごとに別になるため、`-w 4` だと 1 分 10 回制限が実質 1 分 40 回になります。同時処理を増やしたいときは worker を増やすのではなく `--threads 4` を足してください（同一プロセス内ならカウンタを共有できます）。どうしても worker を増やす場合は `RATELIMIT_STORAGE_URI=redis://...` を設定します（別途 `pip install redis`）。
>
> `python3 app.py` での本番起動は `APP_ENV=production` で例外停止します。

### A.4 HTTPS で公開

**Caddy の例**：
```caddyfile
shift.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

### A.5 バックアップ復元演習

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

## 付録 B：なぜ Render と SQLite なのか（選定の根拠）

- **サーバーに Render を選ぶ理由**：GitHub とつなぐだけで公開でき、HTTPS・常時起動・自動バックアップを自動で用意してくれます。初心者でも安全に扱え、利用者 10 人弱なら月 $7 台と低コストです。
- **データベースに SQLite を選ぶ理由**：このアプリは最初から SQLite 向けに作られており、**コードを変えずにそのまま公開できます**。利用者 10 人弱・同時入力が少数という今回の規模では、SQLite で十分に安全・高速です。ファイル 1 つなのでバックアップも簡単です。
- **PostgreSQL / Supabase を今は使わない理由**：どちらも優れていますが、アプリの作り替え（コード改修）と追加コストが必要で、10 人規模には過剰です。将来、利用者や同時アクセスが大きく増えたときの「乗り換え先」と考えてください。
- **Firebase（Firestore）を使わない理由**：表計算のような「行と列」ではなく文書型（NoSQL）のデータベースで、このアプリの作り（リレーショナル＋SQL）とは設計思想が異なります。今回は不向きです。

設計と安全対策の詳しい経緯は [CODE_REVIEW.md](CODE_REVIEW.md) を参照してください。
