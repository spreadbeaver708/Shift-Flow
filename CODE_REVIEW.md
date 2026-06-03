# Shift-Flow セキュリティレビュー（現状版）

最終更新: 2026-06-03 / 対象: Render 公開・4 名試用中（次フェーズ V28 反映）

このドキュメントは「いまの実装で、何から守れているか」を簡潔にまとめたものです。
過去の指摘ひとつひとつの経緯（初期レビュー A〜S や各フェーズの履歴）は Git の履歴を参照してください。

---

## 1. 構成と前提

- **アプリ**: Flask + 標準ライブラリ `sqlite3`（単一ファイル `app.py`）
- **公開**: Render Web Service（Starter）+ 永続ディスク `/var/data`。HTTPS は Render が終端
- **DB**: SQLite（WAL モード）。`/var/data/shift.db` に保存
- **利用者**: 管理者 + 職員 計 10 名弱（試用は 4 名）。各自の個人端末から利用
- **守る資産**: ログイン資格情報（ハッシュ）、シフト希望、備考。**備考に機微情報を入れない運用**を併用

---

## 2. 実装済みの対策（カテゴリ別）

| 領域 | 対策 | 該当 |
|------|------|------|
| 認証 | パスワードは **scrypt** でハッシュ化（Werkzeug 既定 `scrypt:32768:8:1`）。平文保存・平文送信なし | `generate_password_hash` |
| 認証 | ログイン成功時に **`session.clear()`** で旧セッション破棄（セッション固定対策）。session には username のみ保持 | `login()` |
| 認証 | 初回ログイン／管理者リセット後は **パスワード強制変更**まで他画面に進めない | `force_password_change` |
| 認可 | ルートごとに `require_login()` / `require_admin()`。職員の `/admin` は **403** | 各ルート |
| 認可 | `/worker/<name>` は **本人の表示名のみ**許可（他人の画面は menu へ）＝ IDOR 対策 | `worker()` |
| 認可 | 毎リクエストで DB からユーザー状態を再取得。**停止・降格は即時反映**（旧セッション無効化） | `load_current_user` |
| 管理操作 | 自分自身／最後の有効な管理者は**降格・停止不可**。編集は `original_username` を権威とし **ID 改ざん不可**。表示名の重複拒否。UI からの削除は無効化 | `manage_users()` |
| CSRF | `CSRFProtect` を全体適用（exempt なし）。全 POST フォームに `csrf_token`。期限切れは 400 ではなく **ログイン画面へ誘導** | 全テンプレ / `handle_csrf_error` |
| XSS | Jinja2 自動エスケープ有効（`|safe`・`Markup`・`render_template_string` 不使用）。`<script>` 内の変数は **`|tojson`** で安全に埋め込み | テンプレ全般 |
| SQLi | 全 SQL が **プレースホルダ `?`**。文字列連結・f-string による組み立てなし | `app.py` 全 SQL |
| 入力検証 | username / 表示名（URL 危険文字禁止）/ 色（`#RRGGBB`）/ 年月範囲 / 状態（〇×のみ）/ 備考 500 字上限 | 検証ヘルパー群 |
| リダイレクト | 送信後の遷移先は `url_for()` でサーバー生成。**ユーザー制御不可**（オープンリダイレクトなし） | `_remark_modal.html` |
| 秘密情報 | `SECRET_KEY` 未設定なら本番は **起動失敗（fail-fast）**。Render では自動生成 | 起動時 |
| 本番化 | 本番で `debug` 実行を禁止。Cookie は `Secure`(本番)/`HttpOnly`/`SameSite=Lax`。`ProxyFix` は信頼段数明示時のみ | 起動時 |
| エラー | 403/404/500 はカスタムページ。スタックトレースを出さない | エラーハンドラ |
| レート制限 | ログイン・パスワード変更を **10 回/分**で制限（`-w 1`・単一インスタンスでカウンタ整合） | `@limiter.limit` |

---

## 3. 今回（V27）の強化

| 強化 | 内容 | 重大度 |
|------|------|--------|
| パスワード方針 | `isalnum()` 必須を撤廃し **8 文字以上・記号/空白/日本語可・上限 128**（NIST SP 800-63B の考え方＝長さ重視・文字種縛りなし）。旧方針は強い記号入りパスワードを弾く逆効果だった | 中 |
| CSP 追加 | `Content-Security-Policy` を付与。外部リソース読込・フレーム埋め込み・**フォームの外部送信**・`<base>` 注入を遮断。inline 利用のため script/style は `'unsafe-inline'`（nonce 化はフェーズ3） | 中 |
| HSTS 追加 | 本番のみ `Strict-Transport-Security`（1 年・includeSubDomains）。HTTP への降格を防止 | 低 |
| ID 列挙対策 | ログイン失敗時、該当ユーザーが居ない場合も**ダミーハッシュで検証**し応答時間を平準化 | 低 |
| 依存ピン | `Werkzeug>=3.1.6` / `Jinja2>=3.1.6` を明示（下記 CVE を確実に回避） | 低 |
| 静的配信 | 静的ファイルでは `load_current_user` の DB 照会をスキップ（負荷・攻撃面の低減） | 軽微 |

---

## 3.5 次フェーズ（V28）の強化

| 強化 | 内容 | 重大度 |
|------|------|--------|
| アイドルタイムアウト | `PERMANENT_SESSION_LIFETIME`＋`session.permanent`（既定30分・env `SESSION_IDLE_MINUTES`）。無操作で自動ログアウト＝個人端末の置き忘れ対策 | 中 |
| CSP nonce 化 | `script-src` から `'unsafe-inline'` を撤去し **nonce 方式**へ。`base-uri 'none'`。XSS 時の inline スクリプト実行を遮断（inline `style=` を多用するため `style-src 'unsafe-inline'` は当面維持＝別タスク） | 中 |
| キャッシュ抑止 | 認証済みページに `Cache-Control: no-store`（共有/個人端末の戻るボタン対策。**CVE-2026-27205** の緩和も兼ねる） | 低〜中 |
| 監査ログ | `audit_log` に主要操作を記録（ログイン成否・PW変更・ユーザー操作・希望提出・確定保存・CSRF）。**パスワード/ハッシュ/備考本文/CSRFトークンは不記録**。最新1万件保持。閲覧 `/logs` は管理者専用 | 中 |
| username 移行 | シフトを表示名から **`username` 基準**へ非破壊移行（列追加＋backfill）。rename 取りこぼしを解消し、確定シフトの土台に。`name` 列は互換のため残置・併記 | 中 |
| 確定シフト | 希望(`shifts`)と分離した `confirmed_shifts`（`username` 基準・FK・`ON DELETE CASCADE`）。管理者が職員ごとに編集、職員はチーム全体を**読み取り専用**で閲覧 | 機能 |
| 提出状況一覧 | 管理者が月ごとの提出済/未提出・〇日数・最終提出を一覧（`shifts`＋`audit_log` から導出。サマリテーブルは作らない） | 機能 |
| 依存更新 | `Flask 3.1.3`（CVE-2026-27205 修正）/ `Werkzeug>=3.1.8` / Python 3.14.5（GC 安定化） | 低 |

---

## 4. 依存パッケージと既知脆弱性（一次ソース確認済み）

| パッケージ | バージョン | 状況 |
|------------|-----------|------|
| Flask | **3.1.3** | **CVE-2026-27205**（session を `in`/`len` 参照時に `Vary: Cookie` が欠落→キャッシュ汚染、CVSS2.3）を 3.1.3 で修正。本アプリは認証ページに `Cache-Control: no-store` を付与し緩和済みだが確実化のため更新。CVE-2025-47278（`SECRET_KEY_FALLBACKS`）は鍵ローテーション未使用のため**非該当** |
| Werkzeug | **≥3.1.8** | `safe_join` の Windows デバイス名系（**CVE-2025-66221 / CVE-2026-21860 / CVE-2026-27199**）を最新で修正。本アプリは ① Render = Linux ② ユーザー制御のファイルパスを `send_from_directory` で扱わない、ため**非該当**だが確実化のためピン |
| Jinja2 | **≥3.1.6** | **CVE-2025-27516**（サンドボックス回避）を 3.1.6 で修正。本アプリは信頼できないテンプレートを描画しないため**非該当**だが確実化のためピン |
| Flask-WTF | 1.2.1 | CSRF 用。既知の重大 CVE なし |
| Flask-Limiter | 3.8.0 | レート制限用。既知の重大 CVE なし |
| gunicorn | 23.0.0 | 既知の重大 CVE なし |

> 参考（一次ソース）: GitHub Advisory `GHSA-68rp-wp8r-4726`（CVE-2026-27205, Flask）、`GHSA-4grg-w6v8-c28g`（CVE-2025-47278, Flask 鍵フォールバック・非該当）、`GHSA-hgf8-39gv-g3f2`（CVE-2025-66221, Werkzeug）、Werkzeug 3.1.x 公式ドキュメント（`generate_password_hash` 既定 = scrypt）、Render Disks docs（ディスク付与でゼロダウンタイム不可・DB は `.backup` 推奨）。

---

## 5. 検証

- **自動テスト**: `pytest` **82 件すべて成功**（`tests/`）。
- 観点: ログイン/セッション衛生、強制パスワード変更、認可（職員 `/admin`・`/logs`・`/submissions`・`/confirm`=403・停止の即時無効化）、
  `manage_users` の各保護、入力範囲外（month=13 等）で 500 にならない、
  V27 のパスワード方針・CSP・HSTS・ID 列挙対策、
  V28 の CSP nonce（script に `'unsafe-inline'` 無し）・`no-store`・idle timeout（`tests/test_hardening.py`）、
  監査ログの機密値非記録・認可・retention（`tests/test_audit.py`）、提出状況（`tests/test_submissions.py`）、
  確定シフトの保存・読み取り専用閲覧・認可（`tests/test_confirm.py`）、username backfill 移行（`tests/test_db.py`）。

---

## 6. 残課題・受容リスク

V28 で解消済み: **idle timeout** / **CSP の script `'unsafe-inline'`** / **操作の監査ログ** / **シフトの表示名紐づけ**（`username` 化）。
採用した次フェーズ機能（希望/確定の分離・提出状況の一覧・操作ログ）も実装済み。

現時点で**受容**しているリスク（小規模・社内運用のため）:

- **CSP の `style-src 'unsafe-inline'`** — inline `style=` 属性を多用しているため。撤去には全テンプレの CSS 化が必要で視覚回帰リスクが大きく、本アプリは未信頼スタイルの流入経路が無いため実利益が小さい。別タスクとして保留。script 側は nonce 化済みで XSS 実行防御の主要部分は達成。
- **レート制限はインスタンス内メモリ** — 再起動でカウンタ初期化。単一インスタンス（`-w 1`＋ディスク制約）運用なので実害は小。多重化時は Redis。
- **アカウントロックなし（レート制限のみ）／2FA なし** — ロック悪用による正規利用者の締め出し（DoS）を避けるためレート制限で代替。試用〜小規模では受容。
- **管理画面からの専用パスワード再発行は未実装（保留）** — ユーザー編集時のパスワード設定（`must_change_password` 付き）＋ CLI で代替。使用時は `admin_password_set` を監査ログに記録。

### デプロイ時の注意（一次ソース確認済み）
- Render はディスク付与サービスで**ゼロダウンタイムにならない**（再デプロイ時に数秒停止）。低稼働時間帯に実施し、利用者へ事前告知する。
- DB バックアップは disk snapshot restore ではなく **SQLite `.backup`** を使用（`sqlite3 /var/data/shift.db ".backup '/tmp/pre-deploy.db'"`）。デプロイ前に取得し、`PRAGMA integrity_check;` で健全性を確認する。移行は非破壊（列追加＋backfill・`name` 残置）のため後方互換。
