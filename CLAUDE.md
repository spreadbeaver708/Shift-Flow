# CLAUDE.md — AI エージェント向けガイド

Shift-Flow は約10名の職員がスマートフォンからシフト希望を提出し、管理者が締め切り・集計する Flask アプリ。
**Render で公開・運用中**（render.yaml の Blueprint。DB は永続ディスク上の SQLite、単一 gunicorn worker）。
作者・運用者はプログラミング初心者。**簡易・堅牢・安全**が最優先で、機能追加より「壊さないこと」に価値がある。

## ドキュメントの地図

| 読む人 | ファイル |
|---|---|
| 運用者（初心者） | [README.md](README.md) — 使い方・バックアップ・毎月の確認 |
| 開発エージェント | 本書 → [docs/ROADMAP.md](docs/ROADMAP.md)（現在地・保留項目・決定記録）→ [docs/WORK_ORDERS.md](docs/WORK_ORDERS.md)（着手条件つき作業指示書） |
| 履歴（更新しない） | [docs/archive/](docs/archive/) — 過去のレビュー・実装ログ |

**新しい作業を始める前に ROADMAP の着手条件を確認する。** 完了したレビュー文書は docs/archive/ へ移し、ROADMAP を更新する。

## 構成（コードの場所は動かさない）

- `app.py` — 全ルート。**意図的に単一ファイル**（初心者が追えるように。分割は WO-07 の条件を満たすまで禁止）
- `storage.py` — DB 接続・スキーマ移行（SCHEMA_VERSION）・バックアップ（移行前/日次/月次/手動、integrity_check つき）
- `settings.py` — 環境変数の検証。本番は不正値で fail-fast（黙って既定値にしない）
- `security_utils.py` — パスワード方針（8〜128字・弱値拒否・NFC正規化）
- `time_utils.py` — UTC 保存・JST 表示
- `templates/` `static/style.css` — 画面。`tests/` — pytest（2026-07 時点 151件）
- `docs/` — 開発者向け文書。`scripts/` — 運用補助。`.claude/skills/` — プロジェクトスキル（共有）

**app.py・templates/・static/ を移動・改名しない**。Render の `startCommand: gunicorn app:app` と Flask の既定パスが前提。

## コマンド

```bash
# 検証一式（変更後は必ず。/verify-release スキルでも実行可）
PYTHONWARNINGS=error python3 -m pytest -q -p no:cacheprovider
python3 -m py_compile app.py settings.py storage.py security_utils.py time_utils.py
python3 -m pip check
git diff --check
python3 -m pip_audit -r requirements.txt   # 依存を変更したときは必須

# ローカル起動（開発モード。SECRET_KEY 等は自動）
python3 app.py
```

## 変えてはいけない設計判断（理由つき — “改善”しないこと）

1. **CSP は nonce 方式・`unsafe-inline` なし**。inline script は `<script nonce="{{ csp_nonce }}">` のみ。inline style（style属性含む）は禁止 — 色表示は `input[type=color] disabled` スウォッチ方式を使う。
2. **時刻は UTC 保存・JST 表示**（time_utils）。締め切りは「当日 0:00 JST 以降ロック」＝ `now_jst().date() >= deadline`。
3. **パスワードは 8〜128 字・定期変更なし・初回強制変更なし**（NIST SP 800-63B は定期変更を非推奨）。定期変更や複雑性ルールを追加しない。
4. **SQL は全てプレースホルダ**。テンプレートで `|safe` 禁止。JS の DOM 出力は `textContent` のみ（`innerHTML` 禁止）。
5. **管理ルートの認可は `deny_if_not_admin()` に統一**（403 + authz_fail 監査）。例外は「/」だけ（入口 URL のため職員は `/worker` へリダイレクト）。
6. **監査ログ（audit_log）の detail にパスワード・ハッシュ・備考本文・セッション値・CSRF トークンを入れない**（test_audit で固定）。
7. **職員の保存先は `staff_saveable_months()`（前月・当月・翌月）に限定**。前月を含むのは月替わり深夜の送信救済。管理者ルート（`/`・`/staff/<u>`）は無制限（過去修正の業務ニーズ）。
8. **gunicorn は単一 worker・レート制限は `memory://`**。worker を増やす前に必ず WO-03（Redis）。
9. **依存はピン留め**。更新は月次 `pip-audit` の結果に基づき最小限。一括メジャー更新をしない。requirements.txt のコメント（CVE 記録）を消さない。
10. **テストに年月をハードコードしない**。JST 現在月ベース＋`now_jst` の monkeypatch で決定論化する（tests/test_deadline.py が手本）。
11. **文言は初心者向けの平易な です/ます**。専門語（「半角英数記号」「降格」等）を避ける。エラーは「原因＋次にすること」を短く。
12. ユーザー向け画面の flash は base.html が全件表示する。1リクエスト1メッセージを基本にする。

## 作業の進め方

- ブランチ `sin` を最新 `main` から切り、PR を `main` へ。コミットは日本語 `type: 要約` ＋ `Co-Authored-By` 行。
- 変更後は上記コマンドで検証。UI 変更は実画面（モバイル 375px）でも確認。
- **Codex と並行編集がある**。自分がつけていない未コミット差分を revert しない。
- 本番（Render・/var/data）にはコード作業中は触れない。DB を伴う確認はローカルの一時 DB（tests の conftest 参照）か `scripts/restore_rehearsal.sh` の複製で行う。
- レビュー文書を新規作成する場合は `docs/REVIEW_YYYY-MM-DD.md` として作り、完了したら docs/archive/ へ移して ROADMAP を更新する。
