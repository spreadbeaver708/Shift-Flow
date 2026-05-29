# Shift-Flow コードレビュー報告書

- **対象**: カウンセリングルーム シフト管理アプリ（Flask製）
- **構成**（v5.5 時点）: `app.py` / `templates/*`(8ファイル：admin, change_password, help, index, login, manage_users, menu, worker — v1 の result.html はフェーズ2 で削除、help.html はフェーズ2 で追加) / `static/style.css` / `requirements.txt` / `requirements-dev.txt`（v5.5 で追加） / `tests/*`（v5.5 で追加）
- **想定運用**: **インターネット公開**。各スタッフがスマホからシフト希望を入力、管理者が集計・調整。
- **レビュー履歴**:
  - 初版 2026-05-28（Claude Code）
  - v2 2026-05-28 — Codex作成の外部計画書と統合、運用方針を確定
  - v3 2026-05-28 — Codexからの再評価を反映（P/Q/R/S 追加、ロードマップ再構成、`fillForm` 例修正）
  - v4 2026-05-28 — 希望/確定の閲覧モデル明確化、SQLite例の単一化、Cookieは本番限定
  - v4.1 2026-05-28 — Codex 最終評価を反映（フェーズ1閲覧条件補正、`SECRET_KEY` fail-fast、`FLASK_ENV` → `APP_ENV`）
  - v4.2 2026-05-28 — 実装前最終確定版（Codex フォローアップを反映：テンプレを `current_user` に統一、S を 🟡 中に格上げしフェーズ1へ、login 例に `session.clear()`）
  - v5.0 2026-05-28 — 実装完了版（フェーズ0/1/2 を完遂、Codex 連続レビューの後追加指摘も全て反映。詳細は §9 を参照）
  - v5.1 2026-05-28 — 試用前最終レビュー（Claude 自己レビュー + Plan agent 独立第二意見で全ファイル再点検、18 件の findings を §10 に記録。試用前必修 8 件 / 試用前推奨 3 件 / 試用後でよい 7 件）
  - v5.2 2026-05-28 — Codex 第8回レビューを反映（運用事故・初心者目線・テスト不在の盲点を補強。試用前必修に V19/V20 を追加、推奨に V21/V22/V24 を追加、V1 を `must_change_password` で拡張。§7 ロードマップに フェーズ2.5 を新設し具体的スケジュールを記載）
  - v5.3 2026-05-28 — Codex 第9回レビューを反映（件数不整合の修正、CSRF エラーハンドラ実装案を `@app.errorhandler(CSRFError)` に訂正、V20 を `original_username`/`mode` 方式で具体化、V23 に `ALTER TABLE` 冪等マイグレーションと除外パス（`/change_password`, `/logout`, `/static`, `/help`）を明記、V19 を「削除ボタン撤去」に決め打ち、メタ情報（行数）を実数 543 行に更新、§0 K を「フェーズ2.5 / V1, V23」に、§10.7 ブランチ案を §7.1 と整合する 2 ブランチ構成に更新）
  - **v5.4 2026-05-28 — Codex 第10回レビューを反映**（V2 サンプルコードを `session.clear()` → `flash()` → `redirect()` の正しい順序に訂正、V19「撤去 or 二重 confirm」の残存表現を §7/§8/§10.6 で「撤去」に統一、ステータス表記 `v5.2 時点` を `v5.3 時点` に更新、§10.1 に v5.3 時点の総 finding 数 25 件の内訳表を追加、§7.1 Go/No-Go 判定を「ゲート条件」と「完了推奨だが No-Go 条件ではない項目」に分離）
  - **v5.5 2026-05-29 — フェーズ2.5 実装完了版**（単一ブランチ `feature/phase2.5-pre-trial-final` で 試用前必修 11 件 V1〜V8, V19, V20, V23 と 推奨 6 件 V9〜V11, V21, V22, V24 をすべて実装。`tests/` を新設し pytest 39 件すべてグリーン。残りの試用後項目 V12〜V18, V25 はフェーズ2 後半／フェーズ3 で対応予定。詳細は §11 を参照）
- **環境**: Python 3.14.2 / Flask 3.1.0
- **本レビューの範囲**: 報告 → 実装。重大・高リスク項目は実機で再現確認・修正後リグレッション確認済み。

### 現在のステータス（v5.5 時点）

- **フェーズ0/1/2 B案/2.5 完遂**（main マージ前、ブランチ `feature/phase2.5-pre-trial-final` 上で
  pytest 39 件グリーン）。詳細は §9・§11 を参照。
- **試用開始の可否**: §7.1 Go/No-Go 判定の **ゲート条件 7 件中、コードに関する条件はすべて満たした**
  状態。残るは PR レビュー・main マージ・実機チェック（§8）・運用準備（バックアップ復元演習、
  パーミッション設定、職員への使い方共有）。

> ⚠️ **過去の結論（v1 時点、参考のため保存）**:
> v1（初版 2026-05-28）の時点では、**全パスワード漏洩**・**なりすまし**・**管理者画面での任意スクリプト実行**・
> **職員による全同僚の備考閲覧**・**停止/降格後も旧セッションで管理画面アクセス可能** が起こり得る状態だった。
> これらは **フェーズ1（A〜S）と Codex 後追加 C#1〜C#11 の実装で全て解消済み**（§9 実装結果を参照）。
> 現在のリスクは §10 を参照。

> 📌 **確定した運用方針（v4.2 最終確定）**
> 1. **「シフト希望」と「確定シフト」を分ける** … 職員は希望提出、管理者が調整して確定を保存。
> 2. **閲覧範囲は「希望段階」と「確定段階」で別**
>    - **希望段階**: 各職員は **自分の希望のみ** 閲覧・編集可（〇×・備考とも自分のだけ）。
>      他人の希望は **管理者のみ** 閲覧可。
>    - **確定段階**: **全員の〇× を職員も閲覧可**（「誰がいつ出勤か」は職場の公的予定として共有）。
>    - **備考**: 希望段階の備考は **管理者のみ** 閲覧可。**確定シフトは備考を持たない設計**。
> 3. v2/v3/v4 で段階的にユーザー確認・確定した方針。Codex 外部計画書の「全体表ごと管理者専制」案は不採用
>    （シフト透明性とプライバシーを両立する上記モデルを採用）。
> 4. **フェーズ1（試用開始時点）の暫定運用**（v4.1 で明示）
>    確定シフト機能はフェーズ3で導入されるため、フェーズ1の現行 `shifts` は **「希望」相当** として扱う。
>    よって **フェーズ1では `/admin` を管理者専用**（職員メニューから「全体のシフト確認」リンクも削除）とし、
>    職員には自分の希望のみを見せる。**全体〇× の公開は、確定シフト機能を実装するフェーズ3で初めて行う**。

---

## 0. サマリ（重大度順）

凡例: **✅** = 実装済（フェーズ1 または フェーズ2）／**⏳** = 後続フェーズで対応予定

| # | 重大度 | 項目 | 状態 | 実装内容 |
|---|--------|------|------|----------|
| A | 🔴 重大 | パスワード平文保存＋ブラウザへ平文送信 | ✅ Phase1 | `werkzeug.security` でハッシュ化、`manage_users` は `data-*` 属性でパスワード非送信 |
| B | 🔴 重大 | `secret_key` ハードコード | ✅ Phase1 | `SECRET_KEY` 環境変数化、本番 fail-fast、開発のみランダム |
| C | 🔴 重大 | 既知の初期 `admin` / `admin123` | ✅ Phase1 | `ADMIN_INIT_PASSWORD` 環境変数。未指定ならランダム生成しログに一度だけ表示 |
| D | 🟠 高 | CSRF対策が皆無 | ✅ Phase1 | `CSRFProtect`、全 POST フォームに `csrf_token` |
| E | 🟠 高 | 備考の保存型XSS＋改行で機能破損 | ✅ Phase1 | `onclick` 廃止、`data-name`/`data-remark` + `addEventListener` |
| N | 🟠 高 | 職員が全員のシフト・備考を閲覧可 | ✅ Phase1 | `/admin` を管理者専用化（403）、職員メニューからリンク削除 |
| F | 🟠 高 | `REPLACE INTO` による停止解除・重複バグ | ✅ Phase1 | UPDATE/INSERT 明示分岐、`is_active` 維持、PW空欄で据え置き |
| Q | 🟠 高 | 停止/降格後も旧セッションで管理画面到達可 | ✅ Phase1 | `before_request` で DB から `g.user` 再取得、`context_processor` で `current_user` 注入 |
| G | 🟡 中 | 本番 `debug=True` の危険 | ✅ Phase1 | `app.run(debug=False)` + `APP_ENV=production` で直接実行を例外停止 |
| H | 🟡 中 | セッションCookie属性未設定 | ✅ Phase1 | `SECURE`(本番のみ)/`HTTPONLY`/`SAMESITE=Lax` |
| I | 🟡 中 | ログイン試行回数の制限なし | ✅ Phase1 | `Flask-Limiter` で `/login` `/change_password` を 10/分 |
| J | 🟡 中 | シフトを表示名で管理（同名衝突） | ⏳ Phase3（暫定 Phase2） | 試用前の暫定対策として表示名 UNIQUE 検査をアプリ層で追加。`user_id` 化はフェーズ3 §4① と一体実装予定 |
| O | 🟡 中 | 範囲外 year/month で500クラッシュ | ✅ Phase1 | `safe_ym` で範囲検証、status/role/color/備考長も検証 |
| P | 🟡 中 | ログイン時に旧セッションを破棄していない | ✅ Phase1 | `session.clear()` を必ず先行 |
| K | 🟠 高（v5.1 で格上げ） | `change_password` が未ログインで実行可 | ✅ Phase2.5 / V1, V23 | `require_login()` 必須化（V1）＋ `must_change_password` 強制リダイレクト（V23）で対応。詳細は §11.2 |
| L | 🟢 低 | `result.html` 未使用・起動毎 DELETE | ✅ Phase2 | `templates/result.html` 削除、起動時 `DELETE FROM shifts` 撤去 |
| M | 🟢 低 | 依存バージョン未固定 | ✅ Phase1 | `requirements.txt` に Flask/gunicorn/Flask-WTF/Flask-Limiter をピン留め |
| R | 🟢 低 | SQLite 同時書き込み堅牢化未対応 | ✅ Phase2 | `get_db()` に `timeout=30` / `journal_mode=WAL` / `synchronous=NORMAL` / `foreign_keys=ON` |
| S | 🟡 中 | `shift.db` パスが CWD 依存の相対固定 | ✅ Phase1 | `SHIFT_DB_PATH` 環境変数。本番では絶対パス必須（fail-fast） |

### Codex 連続レビューで後追加した項目（フェーズ1/2 で対応済）

| # | 内容 | 状態 |
|---|------|------|
| C#1 | `manage_users` add の検証順序（無効PW時の `shifts.name` 不整合） | ✅ Phase1 |
| C#2 | `init_db` の冪等化（`gunicorn -w 2` 競合） | ✅ Phase1 |
| C#3 | `SHIFT_DB_PATH` 本番絶対パス必須 | ✅ Phase1 |
| C#4 | `Flask-Limiter` の `storage_uri` 明示と `redis` インストール案内 | ✅ Phase1 |
| C#5 | 管理者の自己降格・最後の有効 admin 保護 | ✅ Phase2 |
| C#6 | 表示名重複検査（J の暫定対策） | ✅ Phase2 |
| C#7 | 表示名に `/ \ ? # & < >` 等の URL 危険文字禁止 | ✅ Phase2 |
| C#8 | リバプロ配下の `ProxyFix`（`TRUSTED_PROXY_HOPS`） | ✅ Phase2 |
| C#9 | 旧 DB（平文 PW）からの移行手順を README 化 | ✅ Phase2 |
| C#10 | WAL モードでの `sqlite3 .backup` バックアップ手順 | ✅ Phase2 |
| C#11 | `TRUSTED_PROXY_HOPS` 不正値の明示エラー（fail-fast） | ✅ Phase2 |

---

## 0.5. Codex 連続評価フィードバックの反映状況

### v3 で取り込んだ Codex 再評価（第2回）
| 指摘 | 妥当性 | 反映 |
|------|--------|------|
| 「全体表を職員に見せる」のは方針変更か？ | 誤認（前回のユーザー選択どおり） | §0 注記で意図的 refinement と明記 |
| `PLAN.md` がリポジトリに無い | 妥当 | 参照を「Codex作成の外部計画書」に書き換え |
| F/O/I は公開前に上げたい | 妥当 | フェーズ1 へ昇格（§7） |
| J は最初から `user_id` 化を | 妥当 | §3 J を「直接 `user_id`、表示名UNIQUE は暫定」へ更新 |
| `fillForm` 例にJS文字列埋め込み問題が残る | 妥当 | §1 A を `data-*` 方式に書き換え |
| inline `onclick` → `addEventListener`／CSP | 妥当 | §2 E に推奨を併記 |
| login 時 `session.clear()` | 妥当 | 項目 **P** として追加（フェーズ1） |
| 各リクエストでユーザー状態確認 | **重要** | 項目 **Q** として追加（🟠 高・実機検証） |
| SQLite timeout/WAL/明示TX | 妥当 | 項目 **R** として追加 |
| `shift.db` パス設定化 | 妥当 | 項目 **S** として追加 |

### v4 で取り込んだ Codex 再評価（第3回）
| 指摘 | 妥当性 | 反映 |
|------|--------|------|
| 閲覧方針の最終確認（codexは v3 doc を見て「方針変更では？」と再度 flag） | 誤認だが**最重要**のため再確認 | ユーザーへ最終確認の上、§0 で確定 |
| 「希望」と「確定」のどちらの全体〇× が職員可か曖昧（§0と§4①が不整合） | **妥当**（v3 で明示し損ねた） | §0／§4① を**希望は自分のみ・確定は全体〇× 共有**で明確化 |
| SQLite 例で `isolation_level=None`(autocommit) と `with conn:` が混在 | 妥当 | §3 R を**単一パターン**（既定TX + WAL + `with conn:`）に整理 |
| `SESSION_COOKIE_SECURE=True` は本番HTTPS限定と明記 | 妥当 | §3 H を**環境変数で切替**（ローカルHTTP開発で壊さない） |

### v4.1 で取り込んだ Codex 最終評価（第4回）
| 指摘 | 妥当性 | 反映 |
|------|--------|------|
| **フェーズ1閲覧条件の不整合**（現行 `shifts` は実質「希望」なのに職員全体公開＝§0「他人の希望は管理者のみ」と衝突） | ✓ **完全に妥当**（v4 で残った論理矛盾） | フェーズ1は **`/admin` を管理者専用**へ。全体〇× 公開は確定シフト導入（フェーズ3）と同時に実施 |
| `SECRET_KEY` 未設定時はランダム生成より起動失敗が安全（gunicornワーカー毎に別鍵でセッション崩壊リスク） | ✓ 妥当 | §1 B を **本番 fail-fast、ローカルのみフォールバック** に修正 |
| `FLASK_ENV` は Flask 3 系で曖昧 → 独自 `APP_ENV` に寄せる | ✓ 妥当（FLASK_ENV は Flask 2.3 で非推奨） | §3 H を `APP_ENV=production` ベースに修正 |
| 実装前に `CODE_REVIEW.md` をコミット対象に | ✓ 妥当（運用） | 付記でレビュー記録としてコミット推奨を明記 |

### v4.2 で取り込んだ Codex フォローアップ（第5回・最終確定）
| 指摘 | 妥当性 | 反映 |
|------|--------|------|
| テンプレが `session['role']` のままで Q の即時反映が UI で破れる（旧admin降格後もメニュー上 admin 表示が残る等） | ✓ 妥当 | §2 Q に **`context_processor` を追加**し `current_user` を全テンプレに注入。§2 N の全テンプレ例を `current_user.role` ベースに統一 |
| S（`shift.db` パス固定）は本番 gunicorn 起動と同時に効く事故ポイント。初回試用でも CWD 違いで別DBを作る事故が起き得る | ✓ 妥当 | S を **🟢 低 → 🟡 中** に格上げし、**フェーズ2 → フェーズ1** へ移動 |
| §1 A のログイン例が `session.update(...)` のままで P とコピペ事故の懸念 | ✓ 妥当 | login 例を `session.clear()` + 明示代入の完成形に修正 |

---

## 1. 🔴 重大（試用開始の前提）

### A. パスワードの平文保存＋ブラウザへの平文送信

**現状** — DB平文保存（`app.py:30`、照合 `app.py:65`、`REPLACE` `app.py:154`）。さらに
**ユーザー管理画面の HTML ソースに全員のパスワードが書き出されている**（`manage_users.html:33`
の `onclick="fillForm('{{user[0]}}', '{{user[1]}}', ...)"`）。

**再現確認（実機）** — `/manage_users` の HTML ソースに `fillForm('admin', 'admin123', ...)` がそのまま出力。

**推奨対応**
1. 保存はハッシュ化（`werkzeug.security`、Flask 同梱）。
2. 編集画面はパスワードを**一切ブラウザに送らない**。空欄なら据え置き、入力時のみ更新。
3. **JS文字列に値を直接埋め込まない**（Codex指摘）。`data-*` 属性で渡し、`dataset` で読む。

```python
from werkzeug.security import generate_password_hash, check_password_hash
# 登録・更新時: generate_password_hash(p) を保存
# ログイン照合（P: 旧セッションを必ず破棄してから新規セッションを設定）:
user = conn.execute("SELECT * FROM users WHERE username=? AND is_active=1", (u,)).fetchone()
if user and check_password_hash(user[1], p):
    session.clear()                       # 必ず先に破棄（P 対策）
    session["username"] = user[0]
    session["role"]     = user[2]
    session["name"]     = user[3]
    return redirect(url_for("menu"))
```

```html
<!-- manage_users.html: パスワードは送らない／値は data-* で渡す（JS文字列埋め込み禁止） -->
<button type="button" class="btn-month btn-edit"
        data-username="{{ user[0] }}" data-name="{{ user[3] }}"
        data-role="{{ user[2] }}" data-color="{{ user[5] }}">修正</button>
<script>
document.querySelectorAll('.btn-edit').forEach(btn => {
  btn.addEventListener('click', e => {
    const d = e.currentTarget.dataset;
    f_id.value = d.username; f_name.value = d.name;
    f_role.value = d.role; f_color.value = d.color;
    f_pass.value = '';                     // 編集時は空欄＝据え置き
    submit_btn.innerText = '修正内容を保存';
    window.scrollTo({top:0, behavior:'smooth'});
  });
});
</script>
```

> **移行メモ**: 既存DBには平文が残るので、導入時に全パスワードをリセット（§4③のパスワード再発行と
> 併用）が単純・確実。

### B. `secret_key` のハードコード（git に commit 済み）
`SECRET_KEY` は本番では**環境変数必須**にし、**未設定なら起動を失敗させる**（v4.1 修正）。
ランダム生成にすると **gunicorn の各ワーカーが別々の鍵を持ち、セッションCookieの署名が一致せず
ログイン状態が常に切れる**ため。ローカル開発のみフォールバックを許可する。
```python
import os, secrets

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if os.environ.get("APP_ENV") == "production":
        raise RuntimeError("SECRET_KEY が未設定です（本番では必須）")
    # ローカル開発のみフォールバック（プロセス毎に変わる＝開発用途限定）
    SECRET_KEY = secrets.token_hex(32)
    print("[dev] SECRET_KEY 未設定のためランダム鍵を生成（開発限定）")
app.secret_key = SECRET_KEY
```
- 既存の `cafe_shift_ultra_final_complete_v11` は本番投入前にローテーション
  （変更で既存ログインは全て無効化＝望ましい）。

### C. 既知の初期アカウント `admin` / `admin123`
- 初期パスワードを `ADMIN_INIT_PASSWORD` 等の環境変数から取得・ハッシュ化して作成。
- 未設定ならランダム生成してログに一度だけ表示、初回ログイン後に変更を促す。固定値は排除。

---

## 2. 🟠 高（試用開始の前提）

### D. CSRF（クロスサイトリクエストフォージェリ）対策が皆無
```python
from flask_wtf import CSRFProtect  # requirements.txt に Flask-WTF を追加
csrf = CSRFProtect(app)
```
```html
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">  <!-- 全 <form method="post"> に -->
```

### E. 備考の保存型XSS／改行による機能破損（実機で再現）
**現状** `admin.html:29` の `onclick="alert('【{{ row[1] }}さんの備考】\n{{ row[4] }}')"`
**再現** 備考に `');alert(document.cookie);//` を入れると管理者画面で実行。改行入りでJS構文も破壊。

**推奨対応** — onclick に値を埋め込まず、`data-*` ＋ `addEventListener` で受け渡し（CSP 対応も容易）。
```html
<div class="shift-tag" style="background:{{ row[3] }};"
     data-name="{{ row[1] }}" data-remark="{{ row[4] }}">
    {% if row[4] %}☆{% endif %}{{ row[1] }}
</div>
<script>
document.querySelectorAll('.shift-tag').forEach(el => {
  el.addEventListener('click', e => {
    const d = e.currentTarget.dataset;
    alert("【" + d.name + "さんの備考】\n" + d.remark);  // dataset 経由は安全
  });
});
</script>
```
> **将来**: テンプレ全体で inline `onclick` を撤廃して `addEventListener` に寄せると、
> CSP（`script-src 'self'`）導入の障壁が一気に下がります（§7 フェーズ2 で扱う保守タスク）。

### N. 職員が全員のシフトと備考を閲覧できる（認可・プライバシー）— 実機で再現
**現状** `/admin` は全ログインユーザー可（`app.py:128` は `username` の有無のみ）。`menu.html:28` の
「全体のシフト確認」リンクも職員にまで表示。`admin.html` は全員の備考を表示。
**再現** 職員ログインで `GET /admin` → 200・全体カレンダーと全員の備考が見える。

**推奨対応（フェーズ1 と フェーズ3 で段階的に実装）** — v4.1 で整理

#### フェーズ1（確定シフト機能がまだ無い段階）
現行 `shifts` は実質「希望」なので、§0 方針「他人の希望は管理者のみ」に従い、
**`/admin` を管理者専用に変更**し、`menu.html` から職員向けの「全体のシフト確認」リンクも削除する。
```python
@app.route("/admin")
def admin():
    # Q の before_request で g.user を取得済み
    if not g.user or g.user["role"] != "admin":
        abort(403)
    # 以下、既存の処理
```
```html
{# menu.html: 「全体のシフト確認」は管理者のみに表示（current_user 経由＝v4.2） #}
{% if current_user and current_user.role == 'admin' %}
  <a href="{{ url_for('admin') }}" class="menu-btn btn-confirm">全体のシフト確認</a>
{% endif %}
```

#### フェーズ3（確定シフト導入時に職員へ全体〇× を公開）
§4① の確定シフトページを新設し、そこで **全員の〇× を職員にも公開**（公的予定として）。
備考は希望側にのみ存在し、希望ページでも管理者のみ閲覧可とする。
```html
{# 希望ページ（管理者用）：他人の希望と備考は管理者のみ（current_user 経由＝v4.2） #}
{% if current_user and current_user.role == 'admin' %}
  <div class="shift-tag" style="background:{{ row[3] }};"
       data-name="{{ row[1] }}" data-remark="{{ row[4] }}">
    {% if row[4] %}☆{% endif %}{{ row[1] }}
  </div>
{% endif %}

{# 確定シフトページ（全員可・備考列なし） #}
<div class="shift-tag" style="background:{{ row[3] }};">{{ row[1] }}</div>
```

### F. `REPLACE INTO` による「停止解除」「重複ユーザー」バグ（実機で再現）
- 影響1: 停止した職員を編集すると **無断で復活**（`is_active=0→1`）。
- 影響2: 編集で username を変えると旧行が残り**別人として重複**。

```python
exists = conn.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone()
if exists:
    if new_pw:
        conn.execute("UPDATE users SET password=?, role=?, name=?, color=? WHERE username=?",
                     (generate_password_hash(new_pw), r, n, col, u))
    else:
        conn.execute("UPDATE users SET role=?, name=?, color=? WHERE username=?", (r, n, col, u))
else:
    conn.execute("INSERT INTO users (username,password,role,name,is_active,color) VALUES (?,?,?,?,1,?)",
                 (u, generate_password_hash(new_pw), r, n, col))
```

### Q. 停止／降格後も旧セッションで管理画面に到達できる（認可バイパス）— v3 新規・実機で再現
**現状** — `session["role"]` と `session["name"]` は**ログイン時の値で固定**され、以後DB側で
`is_active` や `role` が変わっても**セッションは更新されない**。各ルートの認可（`app.py:75,118,123,128,143`）
はセッション値だけを見ている。

**再現確認（実機 v3）**
```
[Q-1] 停止した職員の旧セッション
  停止前: GET /menu -> 200
  DB上 is_active=0 に変更後 → GET /menu -> 200, POST /worker -> 302（保存成功・shifts 13件）
[Q-2] worker に降格された旧 admin の旧セッション
  DB上 role=worker に変更後 → GET /manage_users -> 200（管理画面に到達できてしまう）
```

**影響** — 退職・問題行動などで「停止」「降格」しても、当人の旧セッションが残っている限り
**管理機能・データ書き換えが継続可能**。これは認可機構の実質的なバイパス。

**推奨対応** — リクエスト毎に DB から現在のユーザー状態を取得して認可する。`before_request` で集約し、
**テンプレートからも `current_user` で同じ値を見られるよう `context_processor` で注入**する
（v4.2 補強：テンプレが `session['role']` のままだと旧admin降格後にメニューだけ admin 表示が残る）。
```python
from types import SimpleNamespace
from flask import g, abort

@app.before_request
def load_current_user():
    g.user = None
    u = session.get("username")
    if not u:
        return
    conn = get_db()
    row = conn.execute(
        "SELECT username, role, name, is_active FROM users WHERE username=?", (u,)
    ).fetchone()
    conn.close()
    if not row or row[3] == 0:           # 削除 or 停止
        session.clear()                  # 旧セッションを破棄
        return                           # 以後 g.user は None
    g.user = SimpleNamespace(username=row[0], role=row[1], name=row[2])

@app.context_processor
def inject_current_user():
    """テンプレで `current_user.role` 等を使えるようにする"""
    return {"current_user": getattr(g, "user", None)}

def require_login():
    return g.user is not None
def require_admin():
    return g.user is not None and g.user.role == "admin"

# 各ルートの先頭:
# if not require_login(): return redirect(url_for("login"))
# if not require_admin(): abort(403)
```
- 認可判定は `g.user`（DB由来）で行い、`session` の `role/name` には依存しない。
- **テンプレートも `current_user.role`** で参照すること（`session['role']` は使わない）。
  これにより**降格・停止が API だけでなく UI にも即時反映**される（メニューや表示の出し分けが追従）。

---

## 3. 🟡 中・🟢 低

### G. 🟡 本番での `debug=True`
`app.run(debug=True)` はWerkzeugデバッガが露出すれば任意コード実行。本番は gunicorn 起動・debug禁止。

### H. 🟡 セッションCookieの属性（**本番HTTPS限定**で `SECURE=True`）
HTTPS 公開する本番では `SECURE=True` が必須。一方 **ローカル HTTP 開発で `SECURE=True` に
固定するとCookieが送られずログイン維持が壊れる**ため、独自環境変数 `APP_ENV` で切り替える
（**`FLASK_ENV` は Flask 2.3 で非推奨・Flask 3 で運用上曖昧なため使わない**：v4.1 修正）。
```python
PROD = os.environ.get("APP_ENV") == "production"
app.config.update(
    SESSION_COOKIE_SECURE=PROD,         # HTTPS本番のみ True（ローカルHTTP開発では False）
    SESSION_COOKIE_HTTPONLY=True,       # JSから読めない
    SESSION_COOKIE_SAMESITE="Lax",      # クロスサイト送信を抑制
)
```
- `APP_ENV` は本書を通じて統一（B の SECRET_KEY 判定でも使用）。

### I. 🟡 ログイン試行回数の制限なし
`Flask-Limiter` で `/login` と `/change_password` に「1分10回」等の簡易制限。

### J. 🟡 シフトを表示名(`name`)で管理（→ 直接 `user_id` 化）
- **推奨（更新）**: §4① の希望/確定分離と同時に **`shifts(.._requests/_confirmed)` を `user_id` 基準** に
  最初から構築する。`users` に内部ID（`AUTOINCREMENT` or `username` を安定キー）を据え、
  シフトはこのIDで参照。表示名変更で混線しない。
- **暫定（運用直前まで間に合わない場合のみ）**: `users.name` に UNIQUE 制約を付けて
  同名登録を禁止（一時しのぎ。本対応で置き換える）。

### O. 🟡 入力検証の不足（範囲外 year/month で500クラッシュ）— 実機で再現
**再現** `GET /admin?month=13` → `IllegalMonthError` → 500（`/worker` も同様）。
```python
def safe_ym(default_y, default_m):
    y = request.args.get("year", default_y, type=int)
    m = request.args.get("month", default_m, type=int)
    if not (1 <= (m or 0) <= 12): m = default_m
    if not (2000 <= (y or 0) <= 2100): y = default_y
    return y, m
```
- `status` は `{'〇','×'}`、`role` は `{'admin','worker'}`、`color` は `^#[0-9A-Fa-f]{6}$`、
  備考は最大文字数（例 500）に制限。

### P. 🟡 ログイン時にセッションを破棄していない（セッション固定／衛生）— v3 新規
**現状** `app.py:67-68` は `session.update({...})` で**旧セッションに上書き**するだけ。
Flask の署名Cookieセッションでは古典的「セッション固定」自体は緩和されるが、
別ユーザーで連続ログインした場合などに**前ユーザーの session 値が残る**衛生上の問題はある。
**推奨対応**
```python
session.clear()                # まず破棄
session["username"] = user[0]; session["role"] = user[2]; session["name"] = user[3]
```

### K. 🟢 `change_password` が未ログイン・停止状態でも実行可能
ログイン画面からの再設定として意図的なら可。`is_active=0` でも変更できる点と、
「ID＋現PWの当たり判定」に悪用され得る点に注意（I のレート制限と併用）。

### L. 🟢 未使用ファイル・起動毎の副作用
- `templates/result.html` — どのルートからも参照されない**デッドファイル**（削除推奨）。
- `app.py:33` の `DELETE FROM shifts WHERE name NOT IN (...)` は**起動毎**実行（gunicorn ワーカー数分）。
  起動処理から分離し、明示的な管理操作 or 移行処理にする。

### M. 🟢 依存バージョンが未固定
```
Flask==3.1.0
gunicorn==23.0.0
Flask-WTF==1.2.1
Flask-Limiter==3.8.0
python-dotenv==1.0.1
```

### R. 🟢 SQLite 同時書き込み堅牢化未対応
複数スタッフが同時にスマホから保存する運用では、SQLite の既定設定だと「database is locked」が出やすい。
**推奨パターン（既定トランザクション + WAL + `with conn:`）** — 初心者運用でも事故が少ない単一方式。
```python
from contextlib import closing
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)   # 既定の isolation_level（deferred）のまま
    conn.execute("PRAGMA journal_mode=WAL;")     # 読み書きの並行性向上
    conn.execute("PRAGMA synchronous=NORMAL;")   # 性能と耐久性のバランス
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

# 書き込みは with でアトミックに：スコープ終了で自動 COMMIT、例外で自動 ROLLBACK
with closing(get_db()) as conn, conn:
    conn.execute("UPDATE ...")
    conn.execute("INSERT ...")
```
- `with conn:` だけで十分（より高度な `BEGIN IMMEDIATE` 明示は本規模では不要）。
- `with closing(...)` で接続クローズも確実に。

### S. 🟡 `shift.db` パスが CWD 依存の相対固定（**v4.2 でフェーズ1 へ昇格**）
`app.py:14` `sqlite3.connect("shift.db")` は**カレントディレクトリ依存**。本番 gunicorn を
systemd や別ディレクトリから起動すると **CWD 違いで空の別 DB を作って動き始める**事故が
起こりやすく、**初回試用でいきなりデータ消失級の事故**になり得るためフェーズ1必須に格上げ。
```python
DB_PATH = os.environ.get("SHIFT_DB_PATH") or os.path.join(app.instance_path, "shift.db")
os.makedirs(app.instance_path, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    # ...（R の PRAGMA を併せて適用）
    return conn
```
- 本番では `SHIFT_DB_PATH` を **絶対パスで明示**。バックアップ・復元手順もこのパスを基準に。
- 試用開始前に「アプリが読み書きする DB ファイルの絶対パス」をログ等で1度確認することを推奨。

---

## 4. 追加機能の提案（確定方針）

### ① 「シフト希望」と「確定シフト」の分離【採用】
```text
shift_requests(id, user_id, year, month, day, status, remark, submitted_at)   -- 職員の希望（個人プライベート）
shift_confirmed(id, user_id, year, month, day, status, updated_by, updated_at) -- 管理者の確定（職場の公的予定）
```
- **希望**（プライベート）
  - 各職員は **自分の希望のみ** 閲覧・編集可。
  - 他人の希望（〇×・備考とも）は **管理者のみ** 閲覧可。
- **確定**（公的予定）
  - **全員の〇× を職員も閲覧可**（公的シフト表として共有）。
  - **備考列は持たない設計**（必要な伝達は別経路へ）。
- 実装上のメモ
  - 本実装と同時に **J（同名衝突）** を `user_id` 基準で根本解消する。
  - **R（並行性）** も本実装の DB 移行時に同時に整備する。
  - 既存 `shifts` テーブルからの移行手順をマイグレーションとして用意（コード反映前にバックアップ）。

### ② 管理者向け 提出状況ダッシュボード
未提出者一覧／月別提出済みチェック／**締め日**設定／締め後の職員編集ロック。

### ③ パスワード再発行（管理者）
管理者が一時パスワードを発行 → 職員は初回ログイン後に本人が変更（A と相性良）。

### ④ 監査ログ
ログイン成否、ユーザー追加・停止・降格・削除、希望提出、確定更新を記録（インシデント追跡用）。

### ⑤ （任意）開室曜日の設定化
現在 `app.py:95` で日・月・木が `i in [0,1,4]` でハードコード。設定値化で拡張容易。

### ⑥ （任意）確定シフトのCSV/印刷出力

---

## 5. 不要機能・コードの削除／整理 提案

| 対象 | 状態 | 提案 |
|------|------|------|
| `templates/result.html` | 未参照のデッドファイル | **削除** |
| `app.py:33` 起動時 `DELETE FROM shifts ...` | 起動毎の副作用 | 起動処理から分離・明示的管理操作へ |
| `worker.html` と `index.html` | 構造がほぼ重複 | 共通テンプレート化（保守性向上） |
| 各テンプレ大量のインライン `style` | 重複が多く保守難 | 共通CSSクラスへ集約（見た目は不変） |
| `REPLACE INTO`（`app.py:154`） | バグ源（項目F） | UPDATE/INSERT へ |
| インライン `onclick=...` 全般 | XSS・CSP導入の障壁（項目E） | `addEventListener` に統一 |
| `result.html` 経由想定の `members/work_days` 変数 | 死語 | 削除 |

---

## 6. フロントデザインに関する提案（変更はせず提案のみ）

現行デザインは堅持。視認性・操作性は良好。以下は**提案にとどめる**。
- **4原則**: 近接/整列/反復/対比は概ね良好。改善余地はインライン style→共通クラス集約（§5）。
- **色彩**:
  - `--confirm`(オレンジ #FF9800) と `.error`(赤 #FF0000) が近い色相。エラーは彩度/明度差＋アイコン併用で識別性向上。
  - `shift-tag` の背景はユーザー自由設定。**暗い色では黒文字が読めない**。背景輝度で文字色を自動切替:
    ```js
    function autoTextColor(hex){
      const r=parseInt(hex.substr(1,2),16),g=parseInt(hex.substr(3,2),16),b=parseInt(hex.substr(5,2),16);
      return (r*299+g*587+b*114)/1000 >= 140 ? "#000" : "#fff";
    }
    ```
  - 状態（停止/復活など）を色だけでなく文字/アイコンでも表す（色覚多様性配慮）。既に概ね達成。

---

## 7. 修正ロードマップ — 現場での試用開始に向けて

> **試用＝インターネット公開**なので、「公開前必須」「公開後早期」「機能拡充」「保守整備」の
> 4フェーズで進める。フェーズ1がそろうまで試用開始しない。

### フェーズ0：試用開始前の準備（数日）
- 現状のままインターネット公開しない／関係者に周知。
- `shift.db` のバックアップ（既存データがあれば）。
- 既存 `admin/admin123` は試用直前に無効化対象として扱う。
- `CODE_REVIEW.md` をコミット（レビュー記録として残す）。
- フェーズ1 用ブランチを切り、CI で `pip install -r requirements.txt` がグリーンであることを確認。

### フェーズ1：試用開始の前提（公開前必須）
セキュリティ・認可・堅牢性を**ひとまとまりで**修正する。以下が全て終わるまで公開しない。

1. **A** パスワードのハッシュ化＋編集画面から平文排除（`fillForm` を `data-*` 方式へ）
2. **B** `secret_key` の環境変数化＋ローテーション
3. **C** 初期 `admin123` の排除（環境変数 or 初回強制変更）
4. **D** CSRF（Flask-WTF）を全フォームへ
5. **E** 備考XSS／改行バグ修正（onclick 廃止）
6. **N** 認可：**フェーズ1 では `/admin` を管理者専用**（職員メニューから「全体のシフト確認」リンクも削除）。全体〇× の職員公開は §4① 確定シフト導入と同時にフェーズ3 で実施
7. **F** REPLACE バグ修正（UPDATE/INSERT 明示分岐・`is_active` 維持・PWは入力時のみ）
8. **Q** リクエスト毎の DB ユーザー状態検証（停止・降格の即時反映）
9. **P** ログイン時 `session.clear()`
10. **O** 入力検証（year/month 範囲・status・role・color・備考長）
11. **I** `/login` `/change_password` にレート制限
12. **G** debug 禁止の本番起動（gunicorn）／ **H** Cookie属性（Secure/HttpOnly/SameSite）
13. **S** `shift.db` のパスを `SHIFT_DB_PATH` 環境変数 or `app.instance_path` に固定（v4.2 で昇格）
14. **HTTPS で公開**（PaaS自動 HTTPS or リバプロ＋Let's Encrypt）

> **受け入れ基準**: §8 のチェックリストのうち、**A〜I・N・O・P・Q・S** がすべて緑になること。

### フェーズ2：試用初期に並行で進める堅牢化（B 案：試用前に L/R を先取り済み）
15. **L** `result.html` 削除・起動時 DELETE を分離 — **✅ 完了（B案で前倒し）**
16. **M** 依存バージョン固定（Flask, gunicorn, Flask-WTF, Flask-Limiter） — **✅ 完了**
17. **R** SQLite 堅牢化（`timeout` / WAL / 明示TX） — **✅ 完了（B案で前倒し）**
18. **K** `change_password` の仕様整理 — **フェーズ2.5 に格上げ**（V1/V23 として処理）
19. inline `onclick` の全廃→`addEventListener`（CSP導入の前準備） — **試用後 / フェーズ2 後半**

> v4.2 修正: **S はフェーズ1 に移動**（gunicorn 起動と同時に効く事故防止のため）。
> v5.0 修正: **L/M/R はフェーズ2 B案として試用前に完了**。
> v5.1/v5.2 で **試用前必修の追加項目（V1〜V8, V19, V20, V23）が判明**したため、
> 試用開始前に **フェーズ2.5** を挟む方針に更新。

### フェーズ2.5：試用前最終堅牢化（v5.2 新設・公開前必須）

v5.1（自主レビュー）と v5.2（Codex 第8回）で発見された **試用前必修 11 件 + 推奨 6 件 = 17 件**
を着手する。試用開始の最終ゲート。詳細は §10 を参照。

**試用前必修（11件）**:
1. V1 — `change_password` をログイン済み専用に
2. V2 — CSRF 例外時のカスタムハンドラ（UX 救済）
3. V3 — `menu.html` の `alert("{{ ... }}")` を `tojson` に
4. V4 — `index.html` の月切替リンクを `index` に修正
5. V5 — `?submitted=true` を `history.replaceState` で除去
6. V6 — admin 初期パスワード取り扱いの README 注記
7. V7 — `instance/` / DB ファイルパーミッションの README 手順
8. V8 — `worker` 認可失敗時の遷移先を menu / 403 に
9. V19 — ユーザー削除ボタン撤去（停止運用に寄せる）
10. V20 — 修正フォームの username readonly 化
11. V23 — `must_change_password` フラグ + 強制リダイレクト（V1 の拡張）

**試用前推奨（6件）**:
- V9 — 軽量セキュリティヘッダ（`X-Frame-Options` 等）
- V10 — README の `-w 1` 推奨理由を 1 行補足
- V11 — `session["role"]/["name"]` 削除
- V21 — 本書の状態整理（v5.2 で対応中）
- V22 — `tests/` ディレクトリ整備（pytest）
- V24 — README コマンドを `python3` 併記

### フェーズ3：本格運用機能（試用結果を踏まえて 1〜2 か月）
20. **§4①** 希望提出／確定シフトの分離（同時に **J** を `user_id` 化、**確定シフト画面で全員の〇× を職員にも公開**）
21. **§4②** 提出状況ダッシュボード（未提出者・締め日・締め後ロック）
22. **§4③** パスワード再発行（管理者→初回変更、V23 を本格化）
23. **§4④** 監査ログ
24. **§4⑤⑥** 開室曜日の設定化／CSV出力（任意）

### フェーズ4：長期運用の保守性
25. README 化（環境変数・gunicorn・HTTPS・バックアップ/復元手順） — **✅ 完了**
26. SQLite 日次バックアップ＋管理者ダウンロード導線
27. デザインの保守改善（インライン style 集約・worker/index 重複の共通テンプレ化 V25・暗色カラーの文字色自動調整）
28. 監査ログのローテーション・容量監視

---

### 7.1 具体的スケジュール（v5.5 時点 — フェーズ2.5 コード完遂後）

> **前提**: 開発リソースは「ユーザー + Claude」の組み合わせ、1 日あたりの実作業時間は限定的。
> 1 週間 ＝ おおむね 5 営業日換算で見積。
>
> 当初は §10.7 で 2 ブランチ分割案（`security-and-safety` → `ux-and-docs`）を推奨していたが、
> 実装着手時に「単一ブランチ一括」を選択。`feature/phase2.5-pre-trial-final` 1 本で
> 試用前必修 11 件 + 推奨 6 件 + V22 tests を完了させた（詳細は §11）。
> 以下のスケジュールはその選択を反映した v5.5 時点のもの。

| 期間 | 内容 | 状態 |
|------|------|------|
| **〜2026-05-29** | **フェーズ2.5 実装**：V1〜V11, V19〜V24（必修 11 + 推奨 6 + V22 tests） | ✅ 完了（ブランチ `feature/phase2.5-pre-trial-final`、pytest 39 件グリーン、main マージ待ち。詳細 §11） |
| **次の数日** | **PR レビュー → main マージ + 実機・運用準備**（§7.1 末尾の Go/No-Go 参照） | ⏳ 着手予定 |
| **マージ後** | **試用開始**（社内・少人数 3〜5 名・1 か月）。`APP_ENV=production` + 絶対パス `SHIFT_DB_PATH` + Caddy/Nginx 経由 HTTPS + `TRUSTED_PROXY_HOPS=1` + `gunicorn -w 1` | ⏳ |
| **試用初期** | 日次バックアップ稼働、職員からのフィードバック収集、軽微 UX バグ対応、§10.4 の試用後項目（V12〜V18, V25）を順次対応 | ⏳ |
| **試用 1 か月後〜** | **フェーズ3 着手**：§4① 希望／確定シフト分離 + `user_id` 化（J の根本対応）、§4② 提出状況ダッシュボード、§4③ パスワード再発行ワークフロー本格化 | ⏳ |
| **フェーズ3 後半** | §4④ 監査ログ、§4⑤⑥（開室曜日設定化・CSV/印刷出力） | ⏳ |
| **3 か月後以降** | **フェーズ4**：CI（GitHub Actions）、SQLite 日次バックアップ自動化、デザイン保守、監査ログのローテーション | ⏳ |

#### 試用開始の Go / No-Go 判定基準（v5.5 時点）

**ゲート条件（すべて満たさないと試用開始しない）**:

コード側（v5.5 で実装完了）:
- ✅ フェーズ2.5 の試用前必修 11 件（V1〜V8, V19, V20, V23）が全て実装＋pytest 通過
- ✅ V21（本書の状態整理）完了 — 試用判断資料の品質保証
- ✅ V22（`tests/` pytest 整備）完了 — 今後の修正でリグレッション検出可能な状態
- ✅ `pytest` が全件パス（§8 受け入れテストの自動化版、39 件グリーン）

レビュー・マージ・運用準備（試用前に完了させる）:
- ⏳ フェーズ2.5 ブランチを PR 化 → レビュー → main にマージ
- ⏳ 実機（スマホ） + ブラウザで §8 受け入れチェックリストを目視確認
      （特に pytest がカバーしない JS 動作：V5 confirm 再発火防止、V20 修正フォーム readonly UI、V3 flash 表示）
- ⏳ サーバー側のパーミッション設定（V7）と admin 初期パスワード手順（V6）を README 通りに実施
- ⏳ バックアップ手順（`sqlite3 .backup`）を実機で 1 度試して復元可能を確認
- ⏳ 試用関係者（職員 3〜5 名 + 管理者）に「使い方」（`/help` ページ）を共有

**完了推奨だが No-Go 条件ではない項目**（Codex 第10回で明示 → v5.5 で全件実装済）:
- ✅ V9（セキュリティヘッダ）
- ✅ V10（README の `-w 1` 補足）
- ✅ V11（`session["role"]/["name"]` 削除）
- ✅ V24（`python3` 併記）

#### 試用中の継続監視

- 毎週: `journalctl -u shift-flow` 等でエラー / 警告ログをチェック
- 毎日: バックアップが取れていることを確認（`ls -lh /var/backups/shift-flow/`）
- 月初: 前月のシフトデータが残っていることを確認（バックアップから 1 回復元演習）
- 都度: 職員からの問い合わせを Issues に集約、頻度の高いものをフェーズ3 の機能要件に反映

---

## 8. 受け入れテスト（試用開始の合格基準）

凡例: **✅** 自動テスト + 実機検証で確認済（v5.0/v5.2） / **⏳** フェーズ2.5 で追加対応中 / **[ ]** フェーズ3 で対応予定

### 8.1 フェーズ1 完了時の合格基準（すべて緑、v5.0 で達成済）

**🔴 重大・🟠 高**
- ✅ 固定 `secret_key` と `admin123` がコードに存在しない（A/B/C）
- ✅ パスワードが DB にも HTML にも平文で出ない（A）
- ✅ CSRFトークン無しの POST が拒否される（D）
- ✅ 悪意ある備考（`'`・改行・`<script>`）で管理者画面にスクリプト実行されない（E）
- ✅ 職員は `/admin` にアクセスできない（フェーズ1では管理者専用／N）
- ✅ 職員メニューに「全体のシフト確認」リンクが表示されない（N）
- ✅ 職員は `/manage_users` にアクセスできない（既存保護を維持）
- ✅ 停止した職員の旧セッションから `/menu` `/worker` にアクセスできない（Q）
- ✅ worker に降格された旧 admin の旧セッションで `/manage_users` にアクセスできない（Q）
- ✅ 降格された旧adminの旧セッションでメニューに管理者向けリンクが表示されない（Q／テンプレも `current_user` 経由）
- ✅ 停止ユーザーを編集しても勝手に復活しない（F）

**🟡 中**
- ✅ `month=13` や欠落フォームで 500 にならない（O）
- ✅ ログインに `/login` 連打すると一定回数で 429 が返る（I）
- ✅ ログイン直後の session に前ユーザーの値が残らない（P）
- ✅ `debug` が無効、本番は gunicorn 起動（G/H）
- ✅ DB ファイルが `SHIFT_DB_PATH` 等で固定された絶対パスに置かれ、CWD 違いで別 DB が作られない（S）

**🟢 低 / フェーズ2 以降（B 案で前倒し済）**
- ✅ `templates/result.html` が存在しない（L）
- ✅ 依存が `requirements.txt` でピン留め済（M）
- ✅ 同時多発書き込みで「database is locked」が出ない（R）

### 8.2 フェーズ2.5 完了時の合格基準（試用開始の合格基準）

**🟠 試用前必修（v5.1 + v5.2 Codex 第8回）— v5.5 で全件実装完了**
- ✅ `/change_password` がログイン必須、username 欄が無い（V1）— `tests/test_auth.py`
- ✅ 初回ログイン時 `must_change_password=1` の admin / 新規職員は `/change_password` に強制誘導（V23）— `tests/test_auth.py`, `tests/test_db.py`
- ✅ CSRF トークン期限切れ POST がカスタム親切ページに着地（V2）— `tests/test_security.py`
- ✅ `menu.html` の flash 表示が `tojson` 経由で JS 文脈安全（V3）
- ✅ 管理者画面の今月/翌月リンクが `index.html` を指す（V4）— `tests/test_shift_input.py`
- ✅ シフト送信後ブラウザ更新で確認ダイアログが再発火しない（V5）— `history.replaceState`
- ✅ README に admin 初期パスワードのログ運用注意と `chmod 700 / 600` 手順が明記（V6/V7）
- ✅ 他人の `/worker/<name>` を叩いたとき menu へリダイレクト or 403 で混乱しない（V8）— `tests/test_auth.py`
- ✅ 管理画面から「削除」ボタンが撤去され、停止が一次対処として推奨される（V19）— `tests/test_manage_users.py`
- ✅ 修正フォームで username が readonly、ID 改変送信は server 側でも拒否（V20）— `tests/test_manage_users.py`

**🟡 試用前推奨 — v5.5 で全件実装完了**
- ✅ レスポンスに `X-Frame-Options: DENY` / `X-Content-Type-Options: nosniff` 等が付与（V9）— `tests/test_security.py`
- ✅ README の起動コマンドが `python3` 併記（V24）
- ✅ README に「`-w 1` はレート制限ストレージ共有のため」一文（V10）
- ✅ `session["role"]/["name"]` 格納が削除され、`username` 1 本のみ（V11）— `tests/test_auth.py`
- ✅ `tests/` ディレクトリに `pytest` 用テストが整備され、ローカルで全件パス（V22）— 39 件グリーン
- ✅ CODE_REVIEW.md の状態混在が解消され、現状ステータスが冒頭で明確（V21）— 本 v5.5 で対応

### 8.3 フェーズ3 完了時（試用後 1〜2 か月）

- [ ] 同名職員を作っても希望/確定が混線しない（J→`user_id` 化）
- [ ] 管理者が提出状況を確認し、確定シフトを保存できる（§4①②）
- [ ] 職員は他人の希望にアクセスできない（希望は自分のみ）（§4①）
- [ ] 職員は確定の全体〇×を閲覧できる（公的シフト表として共有）（§4①）
- [ ] 確定シフトには備考列が存在しない／表示されない（§4①）
- [ ] 管理者がパスワード再発行できる（§4③、V23 のフロー本格化）
- [ ] 主要操作が監査ログに記録される（§4④）
- [ ] `index.html` と `worker.html` がテンプレ共通化されている（V25）

---

### 付記：本レビューの検証方法・履歴
- Flask の `test_client` で実際のログイン〜操作フローを再現し、**A／E／F／N／O／Q** を実機確認した。
- B／C／D／G・H・I・J・K・L・M・P・R・S はコード静的解析に基づく指摘から実装へ。
- 本報告書の統合履歴
  - 初版（Claude Code）→ v2（Codex 外部計画書を統合）→ v3（Codex 第2回再評価を反映）→
    v4（Codex 第3回再評価を反映＋希望/確定の閲覧モデルをユーザー再確認）→
    v4.1（Codex 最終評価を反映：フェーズ1 閲覧条件補正・`SECRET_KEY` fail-fast・`APP_ENV` 統一）→
    v4.2 実装前最終確定版（Codex フォローアップを反映：テンプレを `current_user` に統一・S をフェーズ1 へ昇格・login 例に `session.clear()`）→
    **v5.0 実装完了版（フェーズ0/1/2 を完遂、Codex 連続レビュー後追加指摘 11件すべて反映、ヘルプページ追加、README を初心者向けに圧縮）**

---

## 9. 実装結果（v5.0 完遂報告）

### 9.1 フェーズ0：試用開始前の準備（完了）
- `CODE_REVIEW.md` をレビュー記録としてコミット
- `feature/phase1-security-hardening` ブランチを切って実装
- 既存 `shift.db` のバックアップ（無いため不要）

### 9.2 フェーズ1：試用開始の前提（完了・main にマージ済）

**実装内容**（PR: `feature/phase1-security-hardening` → main 0661bca）

| 項目 | 主要変更 |
|------|----------|
| A | パスワードを `werkzeug.security` でハッシュ化。`manage_users.html` を `data-*` 属性に書き換え、パスワード平文をHTML/サーバから完全排除 |
| B | `SECRET_KEY` 環境変数化。本番未設定で `RuntimeError`、開発のみランダムフォールバック |
| C | `ADMIN_INIT_PASSWORD` 環境変数。`INSERT OR IGNORE` で `gunicorn -w N` の競合に対応、ログ表示は書き込み成功 worker のみ |
| D | `Flask-WTF` の `CSRFProtect` を有効化、全 POST フォームに `csrf_token` |
| E | `admin.html` の `onclick="alert(...)"` を撤廃、`data-name`/`data-remark` + `addEventListener` |
| F | `REPLACE INTO` を廃止し UPDATE/INSERT 明示分岐、`is_active` を維持、パスワード空欄で据え置き |
| G | `app.run(debug=False)`、`APP_ENV=production` で `python app.py` 直接実行を例外停止 |
| H | `SESSION_COOKIE_SECURE`（本番のみ）/`HTTPONLY`/`SAMESITE=Lax` |
| I | `Flask-Limiter` で `/login` `/change_password` を 10/分。`storage_uri` を明示 |
| N | `/admin` を管理者専用化、`menu.html` から職員の「全体のシフト確認」リンクを削除 |
| O | `safe_ym` で year/month 範囲検証、status/role/color/備考長も検証 |
| P | ログイン成功時に `session.clear()` を必ず先行 |
| Q | `before_request` で DB から `g.user` 再取得、`context_processor` で `current_user` をテンプレに注入 |
| S | `SHIFT_DB_PATH` 環境変数、本番では絶対パス必須（fail-fast） |
| HTTPS | README に Caddy/Nginx + Let's Encrypt のデプロイ手順を明文化 |

**検証**: `test_client` を使った自動テスト 33 件＋実機HTML検査で全項目グリーン。

### 9.3 フェーズ2：試用前堅牢化 B案（完了）

**実装内容**（PR: `feature/phase2-pre-trial-hardening`）

| 項目 | 主要変更 |
|------|----------|
| L | `templates/result.html` 削除、起動時 DELETE は撤去確認 |
| R | `get_db()` に `timeout=30` / `journal_mode=WAL` / `synchronous=NORMAL` / `foreign_keys=ON` |
| バックアップ | README を `sqlite3 .backup` 中心の運用に書き換え。`cp shift.db` 単体は WAL モード下で壊れることを実機検証で確認 |
| C#5 | `manage_users` 全アクションに 3層の admin 保護（自己降格禁止／自己停止・削除禁止／最後の有効 admin の降格・停止・削除禁止） |
| C#6 | 表示名重複検査をアプリ層で追加（J の暫定対策） |
| C#7 | 表示名に `/ \ ? # & < >` 改行/タブ/NUL を禁止する `NAME_FORBIDDEN_RE` |
| C#8 | `TRUSTED_PROXY_HOPS` 環境変数 + `ProxyFix`（既定 0 で適用なし、Caddy/Nginx 経由なら 1） |
| C#9 | 旧 DB（平文 PW）からの移行手順を README に明記 |
| C#10 | WAL モードでの `sqlite3 .backup` 推奨手順、復元時の sidecar 削除 |
| C#11 | `TRUSTED_PROXY_HOPS` 不正値で素の `ValueError` を明示 `RuntimeError` に翻訳 |

**並行性検証**: 4プロセス × 50回 = 200 件の並行 INSERT で `database is locked` 0 件、WAL 有効化で 40% 高速化（0.20s → 0.12s）。

### 9.4 追加対応

- **ヘルプページ** `/help` を追加（`templates/help.html`）。役割（職員/管理者/未ログイン）別に表示内容を出し分け。`menu.html` と `login.html` からリンク。
- **README** を初心者向けに刷新（203行 → 111行、約 45% 圧縮）。コマンド先行型のクイックスタート、環境変数一覧表、トラブルシュート表を整備。

### 9.5 後続フェーズ予定（試用開始後）

- **フェーズ2 残**: K（`change_password` 仕様整理）、inline `onclick` の全廃 → `addEventListener`（CSP 導入準備）
- **フェーズ3**: §4① 希望/確定シフト分離・J の本対応（`user_id` 化）、§4② 提出状況ダッシュボード、§4③ パスワード再発行、§4④ 監査ログ
- **フェーズ4**: 日次バックアップ自動化、デザイン保守改善、監査ログのローテーション

### 9.6 試用開始時の運用チェックリスト

| 項目 | 値 |
|---|---|
| `APP_ENV` | `production` |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` の出力 |
| `SHIFT_DB_PATH` | 絶対パス（例 `/var/lib/shift-flow/shift.db`） |
| `TRUSTED_PROXY_HOPS` | リバプロ配下なら `1`、直接公開なら `0` |
| `ADMIN_INIT_PASSWORD` | 初回のみ・十分長いランダム値 |
| gunicorn | 初期は `-w 1`（複数 worker 時は `RATELIMIT_STORAGE_URI=redis://...` 推奨） |
| HTTPS | PaaS 自動 or Caddy/Nginx + Let's Encrypt |
| バックアップ | `sqlite3 shift.db ".backup '...'"` を cron 日次 |

---

## 10. 試用前最終レビュー（v5.1）

### 10.1 背景

v5.0 でフェーズ0/1/2 完遂・Codex 後追加 C#1〜C#11 反映済。本セクションは
**試用開始（インターネット公開）直前** の最終チェックとして、Claude（自己レビュー）と
Plan agent（独立第二意見）の 2 視点で全ファイルを再点検した結果を記録する。

レビュー対象（v5.3 時点）: `app.py`（543行）/ `templates/*.html`（8ファイル）/ `static/style.css` /
`requirements.txt` / `README.md` / `CODE_REVIEW.md`。

**v5.3 時点の総 findings 数: 25 件**

| 区分 | v5.1（自主 + Plan agent） | v5.2（Codex 第8回） | 合計 |
|------|----|----|----|
| 🟠 試用前必修 | 8 件（V1〜V8） | 3 件（V19, V20, V23） | **11 件** |
| 🟡 試用前推奨 | 3 件（V9, V10, V11） | 3 件（V21, V22, V24） | **6 件** |
| 🟢 試用後でよい | 7 件（V12〜V18） | 1 件（V25） | **8 件** |
| 合計 | 18 件 | 7 件 | **25 件** |

v5.3 では Codex 第9回・第10回の指摘で各 finding の修正方針が具体化された
（件数増減なし、内容のブラッシュアップのみ）。
§0 サマリへの統合は試用前必修 K（→V1/V23）のみ反映済、その他は §10 を参照。

凡例: **🟠 試用前必修** ／ **🟡 試用前推奨** ／ **🟢 試用後でよい**

### 10.2 試用前必修（11件）

> 内訳: v5.1 で発見 8 件（V1〜V8）+ v5.2 Codex 第8回で追加 3 件（V19, V20, V23）。
> V23 は V1 の派生（`must_change_password` 強制）として別項目化したもの。

#### V1. 🟠 `change_password` がログイン不要の総当たり経路
- 場所: `app.py:495-519`
- 問題: 未ログインで誰でも叩け、`(username, password_current, password_new)` で検証する。
  `/login` と並列の「username＋現PWを当てに行く」攻撃面が存在。レート制限はあるが IP 単位なので
  分散攻撃で迂回可能。
- 修正方針: `require_login()` を必須にし、`username` フォーム項目は廃止（`g.user.username` を使う）。
  `change_password.html` の username 入力欄も削除。login.html の「PASSWORDを変更」リンクは
  ログイン後メニュー側に移す。
- §0 サマリの K（試用後分類）を **試用前必修に格上げ**。
- **拡張（V23: Codex 第8回指摘・第9回で具体化）**: 初回ログイン時のパスワード変更を強制したい。

  **(a) DB マイグレーション（冪等）**:
  `init_db()` 内で以下を冪等に実行する（既存 DB / 新規 DB どちらでも安全）:
  ```python
  cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
  if "must_change_password" not in cols:
      conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER DEFAULT 0")
  ```
  admin 作成（V6 と同じ初期化経路）と、管理者によるパスワード設定（`manage_users` の add アクションで
  パスワード入力ありの場合）は **`must_change_password=1` をセット**。
  本人が `/change_password` で変更したら **0 に戻す**。

  **(b) `before_request` での強制リダイレクト**:
  ```python
  ALLOWED_WHEN_MUST_CHANGE = {"change_password", "logout", "static", "help_page"}
  if g.user and g.user.must_change_password and \
     request.endpoint not in ALLOWED_WHEN_MUST_CHANGE:
      return redirect(url_for("change_password"))
  ```
  除外パス（Codex 第9回で明示）:
  - `/change_password`（変更画面本体）
  - `/logout`（諦めてやり直しもできるように）
  - `/static/*`（CSS が当たらないと UI が崩壊して詰む）
  - `/help`（操作不明時のリファレンス）
  これにより本人がパスワードを変えるまで他の画面に進めない。

  **(c) `load_current_user` 拡張**: 既存 SELECT に `must_change_password` 列を追加し、
  `g.user.must_change_password` で読めるようにする。

  **(d) ヘルプの「必ず変更してください」表記とコードを一致させる**（help.html L37）。

#### V2. 🟠 CSRF 例外時の挙動が UX 破壊
- 場所: `app.py`（`CSRFProtect(app)` の既定動作）
- 問題: スマホで長時間放置 → 送信時に CSRF トークン期限切れで素の 400 が出る → 職員から見ると
  「シフトを出したつもりが消えた」事故になる。
- 修正方針: **`CSRFProtect` 自体には `error_handler` メソッドは無い**ため、Flask の `errorhandler`
  デコレータで `CSRFError` を捕捉する（Codex 第9回指摘で訂正、第10回で順序事故を修正）:
  ```python
  from flask_wtf.csrf import CSRFError

  @app.errorhandler(CSRFError)
  def handle_csrf_error(e):
      session.clear()  # 先にセッションをクリア
      flash("セッションが切れました。もう一度ログインしてください。")  # flash は session 経由なので clear の後
      return redirect(url_for("login"))
  ```
  **重要**: `flash()` は内部で session に保存するため、`session.clear()` を `flash()` の後に書くと
  メッセージも消える事故になる（Codex 第10回指摘）。必ず `session.clear()` → `flash()` → `redirect()`
  の順にすること。
  ログイン画面に着地させれば、ログイン後に再度シフト入力を促す自然なフローになる。
  POST されたフォーム内容は復元しない方針（再送信は職員にとっても確認の機会になる）。

#### V3. 🟠 `menu.html:35` の `alert("{{ messages[0] }}")` は JS 文脈で危険
- 場所: `templates/menu.html:35`
- 問題: Jinja の HTML エスケープは JS 文字列リテラル内では適切でない。現状の flash 発火元は
  固定文字列だが、`manage_users` の `flash(f"... ID: {dup[0]} ...")` のように username 値が
  混ざる経路がすでに存在する（`USERNAME_RE` で記号は制約済だが、テンプレ側でも防御すべき）。
- 修正方針: `{{ messages[0] | tojson }}` に置換。

#### V4. 🟠 `index.html` の月切替リンクが壊れている（バグ）
- 場所: `templates/index.html:15-20, 83`
- 問題: 管理者画面の今月/翌月リンクが `url_for('worker', name=name, ...)` を指している。管理者が
  翌月を押すと `/worker/<管理者名>` に遷移し worker.html がレンダリングされる UX 不整合。
  app.py L296 の POST 後リダイレクトは正しく `index` を指しているため、リンク側だけが矛盾。
- 修正方針: `url_for('worker', ...)` → `url_for('index', ...)` の 3 箇所修正。

#### V5. 🟠 `?submitted=true` がブラウザ更新で再発火（バグ）
- 場所: `templates/worker.html:104-116`, `templates/index.html:77-89`
- 問題: POST → 303 → GET `?submitted=true` で confirm を出す現状は、ブラウザ更新で confirm が
  再表示。ユーザーが「もう一度送信した？」と混乱。
- 修正方針: confirm の直前か直後に `history.replaceState(null, '', location.pathname)` で
  クエリを除去。

#### V6. 🟠 admin 初期パスワードがサーバーログに残存する運用リスク
- 場所: `app.py:155-159` の `print(...)`
- 問題: `print` の出力は gunicorn / journald / systemd-cat 経由でサーバーログに永続化される。
  本人が控えても、ログを見られる他者にも漏れる。
- 修正方針: コードは現状維持で可。README §トラブルシュート と §本番デプロイ に
  「初期パスワード控えたらログから削除すること」「`ADMIN_INIT_PASSWORD` を環境変数で渡せば
  ランダム生成のログ出力は出ない」を明記。

#### V7. 🟠 `instance/` / DB ファイルのパーミッションが umask 依存
- 場所: `app.py:96-100` の `os.makedirs`、`get_db()` の `sqlite3.connect`
- 問題: 本番サーバーで他ユーザーから読めると、パスワードハッシュ＋備考が流出する。
- 修正方針: README §本番デプロイ に以下を追記：
  ```bash
  install -d -m 700 /var/lib/shift-flow
  # 起動後に
  chmod 600 /var/lib/shift-flow/shift.db*
  ```
  systemd unit を使う場合は `UMask=0077` の併用も推奨。

#### V8. 🟠 `worker` ルートの認可失敗時にログイン画面へ飛ばす
- 場所: `app.py:321-322`
- 問題: 認証済みでも他人の `/worker/<name>` を叩くとログインへリダイレクト。
  「ログアウトされた？」と混乱を招く。
- 修正方針: `abort(403)` または `flash("自分のシフト入力画面以外にはアクセスできません")` →
  `redirect(url_for("menu"))`。

#### V19. 🟠 ユーザー削除が不可逆＋シフト履歴も即削除（Codex 第8回、第9回で決め打ち）
- 場所: `app.py:466-487`（`action == "delete"` 分岐）, `manage_users.html` の「削除」ボタン
- 問題: 「削除」ボタンを押すと `DELETE FROM shifts WHERE name=?` で過去シフト履歴も同時消失。
  初心者の誤操作で**取り返しのつかないデータ消失事故**になり得る。「停止」と「削除」が
  並んでいて誤クリックも誘発しやすい。
- 修正方針（Codex 第9回で決め打ち）: **試用初期は「削除」ボタンを `manage_users.html` から
  完全に撤去する**。サーバー側 `action == "delete"` ハンドラも、ボタン経由では呼ばれないが
  念のため `flash("削除は管理操作で行ってください。停止で十分なケースが大半です。")` で弾く。
  - 停止（`is_active=0`）で十分なケースが大半。ヘルプにも「退職時は停止、削除は使わない」を明記。
  - 物理削除が必要な場合は **バックアップ取得後の管理 CLI 操作**（`sqlite3 shift.db
    "DELETE FROM ..."`）に限定する運用に寄せる。README §トラブルシュート に手順を追記。
  - フェーズ3 で監査ログ（§4④）と確定シフト機能が入った後、改めて UI 上の削除フローを設計する
    （その時点では「削除依頼 → 監査ログ → バックアップ → 物理削除」の多段プロセス化を想定）。

#### V20. 🟠 修正フォームの username が編集可能で新規ユーザー誤作成（Codex 第8回）
- 場所: `templates/manage_users.html:22`（`<input type="text" name="username" id="f_id" required>`）,
  `app.py:368`（`existing = ... WHERE username=?` 判定）
- 問題: 「修正」ボタンで `fillForm` が動き ID 欄に既存 username をセットするが、**ID 欄は
  readonly でない**ため、ユーザーが ID を書き換えると `existing` 判定が外れて新規ユーザーが
  作成される。「太郎の表示名と色を修正したつもり」が「太郎は別人に上書き、自分は新規 username
  で作成」になり混乱。
- 修正方針（Codex 第9回で具体化）:
  1. **UI 側**: 修正モードのときだけ username 欄を `readonly` にする
     （`fillForm` 内で `f_id.readOnly = true` + 視覚的に薄い背景色、新規モードでは false に戻す）。
  2. **フォームに `mode` を明示**: 隠しフィールド `<input type="hidden" name="mode" value="create">`
     を持ち、修正ボタン押下時に `value="edit"` + 隠しフィールド `original_username` に現 ID を保持。
     送信時は `mode` を必ず読み、`mode=edit` なら username は `original_username` 由来に固定して
     フォーム上の username 入力値は無視する（DB 検索キーが書き換わらないことを保証）。
  3. **サーバー側の二重防御**: `mode=edit` で `original_username` と存在ユーザーが一致しなければ
     `flash("ID 変更は禁止です。停止 → 削除 → 新規登録の手順で行ってください。")` で弾く。
     `mode=create` で existing が見つかった場合も「重複登録」として弾く。
  4. ID 変更の根本対応は §0 J（`user_id` 化）でフェーズ3 に解消。

### 10.3 試用前推奨（6件）

#### V9. 🟡 セキュリティヘッダ最低限
- 場所: `app.py` 全体（`@app.after_request` 未実装）
- 問題: `X-Frame-Options` / `X-Content-Type-Options` / `Referrer-Policy` 無し。
  クリックジャッキング・MIME sniffing の最低限の防御がない。
- 修正方針: 軽量な `@app.after_request` で
  ```
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: same-origin
  ```
  を付与。Flask-Talisman を入れずに 5 行で済む。CSP は inline `onclick` 撤廃後（フェーズ2 後半）で良い。

#### V10. 🟡 README に `-w 1` 推奨理由を 1 行補足
- 場所: `README.md:38`
- 問題: `gunicorn -w 1` の理由が散在していて初心者には繋がりが見えない。
- 修正方針: 「memory ストレージのレート制限を共有するため、複数 worker は Redis 設定後にだけ有効」
  を 1 行追記。

#### V11. 🟡 `session["role"]/["name"]` の格納は事実上のデッドコード
- 場所: `app.py:254-255`
- 問題: `load_current_user`（L204）は `session["username"]` だけ読む。role/name は格納のみで未使用。
  テンプレで `session.role` を参照する誤った修正が将来混入したとき、Q（停止/降格の即時反映）が
  破れる温床。
- 修正方針: L254-255 を削除し、session には `username` だけ入れる。整理目的、リグレッション無し。

#### V21. 🟡 CODE_REVIEW.md の状態が混在（Codex 第8回）
- 場所: `CODE_REVIEW.md`（冒頭警告文と §8 受け入れチェックボックス）
- 問題: 「試用開始可能」（v5.0）と「現状のまま公開しないで」（v1）が混在し、§8 受け入れテストの
  チェックボックスも未チェックのまま残っている。**運用判断に使う文書として誤解の元**になる。
- 修正方針: 本 v5.2 で対応済み:
  1. 冒頭の警告ブロックを「過去の結論（v1 時点、参考のため保存）」と明示
  2. 「現在のステータス（v5.2 時点）」ブロックを冒頭に追加し、フェーズ2.5 未着手を明記
  3. §8 受け入れテストのチェックボックスをフェーズ1/2 実装済項目で ✅ 化（後続のセクションで実施）

#### V22. 🟡 自動テストがリポジトリ内に無い（Codex 第8回）
- 場所: リポジトリ全体（`tests/` ディレクトリ無し）
- 問題: §9 で「自動テスト 33 件＋4プロセス並行性検証 通過」と記録されているが、テストファイル本体は
  `/tmp` で実行して破棄しており、リポジトリには残っていない。**今後の修正で同じ検証ができず、
  リグレッションが入っても気付けない**。
- 修正方針: `tests/` ディレクトリを作り、`pytest` ベースで以下を移植・整備:
  - `tests/conftest.py` — 一時 DB / `APP_ENV` / `SECRET_KEY` 等のフィクスチャ
  - `tests/test_auth.py` — ログイン、CSRF、レート制限、停止/降格セッション無効化（§8 必修）
  - `tests/test_manage_users.py` — 自己降格保護・最後 admin 保護・表示名重複・禁止文字
  - `tests/test_shift_input.py` — シフト POST、入力検証
  - `tests/test_db.py` — WAL PRAGMA、並行書き込み、`sqlite3 .backup` 検証
  - `tests/test_config.py` — `TRUSTED_PROXY_HOPS` fail-fast、`SHIFT_DB_PATH` 必須化
  - `requirements-dev.txt` に `pytest`, `pytest-flask` を追加（`requirements.txt` 本体は据え置き）
  - `README.md` に `pytest` 実行手順を追記
  - CI（GitHub Actions）も追加（試用後でよいが、最初の `pytest` 実行手順だけは試用前に）

#### V24. 🟡 README のコマンドが `python` 前提（Codex 第8回）
- 場所: `README.md:12`（`python app.py`）
- 問題: macOS / 多くの Linux 環境では `python` コマンドが無く `python3` のみ。
  初心者が `python: command not found` で詰まる。
- 修正方針: `README.md` のコマンド例を `python3 app.py` に変更し、Windows 想定の
  `python app.py` も併記。`pip` も同様に `python3 -m pip install -r requirements.txt`
  を推奨形にする。

### 10.4 試用後でよい（既知・記録済を含む 8件）

| # | 項目 | 状態 |
|---|------|------|
| V12 | inline `onclick` 撤廃（worker.html / index.html 備考モーダル） | §7 フェーズ2 後半で予定済 |
| V13 | パスワードルール強化（記号許可、長さ 8+） | 既知。試用後で可 |
| V14 | 500/404/403 のカスタムエラーページ | 既知。試用後で可 |
| V15 | `change_password.html` に flash 表示なし | 機能上は OK、cosmetic |
| V16 | `safe_ym` の URL 改変時の無音フォールバック | 影響軽微 |
| V17 | `/login` GET のレート制限なし | 実害薄、IP 単位制限あり |
| V18 | `shifts.name` 連動の根本解消 | §0 J / §4① で `user_id` 化として記録済（フェーズ3） |
| V25 | `index.html` と `worker.html` のテンプレ重複解消（Codex 第8回） | 共通テンプレ化＋ Jinja `include` で 80 行 → 50 行程度に圧縮可。V4 で月リンク修正後にやると影響範囲が小さい。フェーズ2 後半に予定 |

### 10.5 不要なコード・機能の所見

明確な死コードはほぼ無し（フェーズ2 で `templates/result.html` と起動時 DELETE は撤去済）。
強いて挙げれば V11 の `session["role"]/["name"]` 格納が機能上未使用なため整理対象。
app.py 543 行＋テンプレ 8 ファイルに対して過剰な抽象化・冗長処理は見られず、保守性は良好。

### 10.6 動作確認の現状と未検証項目

**v5.0 までに自動テスト＋実機検証で確認済**:
- 認可（職員 /admin 403、停止職員旧セッション無効化、降格 admin の旧セッション無効化）
- パスワードハッシュ化と HTML 非出力
- CSRF 400 拒否 / レート制限 429
- WAL モードと 4 プロセス × 50 並行書き込み（locked 0 件）
- `sqlite3 .backup` で WAL 未反映分も復元（vs `cp` で空）
- 管理者の自己降格禁止 / 最後 admin 保護 / 表示名重複拒否 / 禁止文字拒否
- ProxyFix の正常動作と不正値 fail-fast

**v5.1 修正後に追加で確認すべき項目**:
- V1: 未ログインで POST `/change_password` → 302（または 401）
- V2: CSRF トークン無し / 期限切れ POST → カスタムページ表示、UX 親切
- V4: 管理者ログイン → `/?year=2026&month=7` → admin ではなく index.html が表示
- V5: シフト送信後 confirm を「いいえ」→ ブラウザバックで `?submitted=true` が残らない
- V9: 全レスポンスのヘッダに `X-Frame-Options: DENY` 等が含まれる
- V11: テンプレが `current_user.*` のみで描画される（session ローカル参照ゼロ）
- V19: 「削除」ボタンが `manage_users.html` から消えていること、サーバー側でも `action=delete` が拒否されること
- V20: 修正モードで username 欄が readonly、ID 改変送信時のサーバー側拒否
- V23: 新規ユーザーが初回ログイン後、強制的に `/change_password` へ誘導される
- 実機: スマホでログイン → 30 分放置 → 送信 → CSRF エラーで親切な画面に着地

**Codex 第8回（v5.2）の実機確認**:
Codex はリポジトリの現状で以下を一時 DB 上で確認済（編集なし、すべて緑）:
- `python3 -m py_compile app.py` 成功
- CSRF なし POST → 400
- ログイン成功 → 302（メニュー）
- 管理画面 HTML に平文パスワード非出力
- 職員の `/admin` → 403
- 停止済み旧セッションで `/menu` → ログインへリダイレクト
- `GET /admin?month=13` → 500 にならず 200 復帰
- `/login` 失敗 11 回目で 429
- 本番 `SECRET_KEY` 未設定 → 起動失敗
- 本番 `SHIFT_DB_PATH` 相対 → 起動失敗

これによりフェーズ1/2 の主要スモークは「v5.2 時点で再現確認済み」と裏付けられた。

### 10.7 推奨される修正ブランチの切り方（v5.3 で更新）

§7.1 のスケジュールと整合する形で、以下の **2 ブランチ分割**を推奨:

- **Week 1**: `feature/phase2.5-security-and-safety` — 必修のうちセキュリティ・運用事故防止系
  - V1 — `change_password` をログイン済み専用
  - V2 — CSRF エラーハンドラ
  - V19 — ユーザー削除ボタン撤去
  - V20 — username readonly + `mode/original_username` 防御
  - V23 — `must_change_password` 強制リダイレクト + DB マイグレーション
  → 試用開始の最低ライン。

- **Week 2**: `feature/phase2.5-ux-and-docs` — 残り必修と推奨をまとめて
  - V3, V4, V5, V8 — UI バグ / XSS パターン / 認可遷移
  - V6, V7, V10, V24 — README 補強
  - V9 — セキュリティヘッダ
  - V11 — `session["role"]/["name"]` 削除
  - V21 — 本書の状態整理（v5.2 で対応中）
  - V22 — `tests/` pytest 整備（このブランチか、Week 2 末の独立ブランチ）

- **代替案**: 単一ブランチ `feature/phase2.5-pre-trial-final` で必修 11 件 + 推奨 6 件を一括 PR。
  PR レビューと検証は重くなるが、`tests/` 整備で同時に検証できる利点あり。
  着手時にユーザーの判断で選択。

### 10.8 修正対象ファイル（参考）

| Finding | 変更ファイル |
|---------|--------------|
| V1 (change_password) | `app.py`, `templates/change_password.html`, `templates/login.html` (リンク撤去) |
| V2 (CSRF handler) | `app.py`（`from flask_wtf.csrf import CSRFError` + `@app.errorhandler(CSRFError)` 追加） |
| V3 (alert tojson) | `templates/menu.html` |
| V4 (月切替リンク) | `templates/index.html`（3 箇所） |
| V5 (submitted 除去) | `templates/worker.html`, `templates/index.html`（同 JS パターン） |
| V6 (ログ運用) | `README.md` |
| V7 (パーミッション) | `README.md` |
| V8 (worker 403) | `app.py` |
| V9 (ヘッダ) | `app.py`（`@app.after_request` 追加） |
| V10 (`-w 1` 解説) | `README.md` |
| V11 (session 整理) | `app.py`（L254-255 削除のみ） |

---

## 11. 実装結果（v5.5 — フェーズ2.5 完遂報告）

### 11.1 ブランチ・スコープ

- ブランチ: `feature/phase2.5-pre-trial-final`（単一ブランチ一括方式を採用）
- スコープ: §10.7 代替案。試用前必修 11 件（V1〜V8, V19, V20, V23）+ 試用前推奨 6 件（V9, V10, V11, V21, V22, V24）の計 17 件。

### 11.2 実装内容

| 項目 | 主要変更 |
|------|----------|
| V1 | `/change_password` を `require_login()` 必須化、`username` フォーム欄を削除し `g.user.username` を使う。`login.html` の「PASSWORDを変更」リンクを撤去し `menu.html` に移設。 |
| V2 | `from flask_wtf.csrf import CSRFError` + `@app.errorhandler(CSRFError)` を追加。`session.clear()` → `flash()` → `redirect(login)` の順で UX 救済。 |
| V3 | `menu.html` の `alert("{{ messages[0] }}")` を `alert({{ messages[0]\|tojson }})` に置換。 |
| V4 | `index.html` の月切替リンク 2 箇所 + confirm 後のリダイレクト 1 箇所を `url_for('worker', ...)` から `url_for('index', ...)` に修正。 |
| V5 | `worker.html` / `index.html` の `submitted=true` 処理に `history.replaceState(null, '', location.pathname)` を追加（confirm 前に呼び出し）。 |
| V6 | README §本番デプロイ §1 に「`ADMIN_INIT_PASSWORD` を環境変数で渡せばランダム生成ログ出力なし」「ログを 1 度控えたら削除」の運用指示を明記。 |
| V7 | README §本番デプロイ §2 に `install -d -m 700` と `chmod 600 shift.db*`、`UMask=0077` の手順を明記。 |
| V8 | `worker(name)` の認可失敗時を `redirect(url_for("login"))` から `flash("自分のシフト入力画面以外にはアクセスできません") + redirect(url_for("menu"))` へ変更。 |
| V9 | `@app.after_request add_security_headers` を追加。`X-Frame-Options: DENY` / `X-Content-Type-Options: nosniff` / `Referrer-Policy: same-origin` を `setdefault` で付与。 |
| V10 | README §本番デプロイ §3 に「`-w 1` 推奨理由 = memory ストレージのレート制限を共有するため。worker 増やすなら Redis」を明文化。 |
| V11 | `/login` 成功時の `session["role"] = ...` / `session["name"] = ...` を削除。session には `username` のみ保存。 |
| V19 | `manage_users.html` から「削除」フォーム/ボタンを撤去。サーバー側 `action == "delete"` は `flash("削除は管理操作で行ってください...")` で一律拒否。README §ユーザーの完全削除 に sqlite3 CLI 手順を追記。 |
| V20 | `manage_users.html` に hidden `mode` / `original_username` を追加し、修正時は `f_id` を `readOnly` に。サーバー側は `mode=edit` のとき `u = original_username` で権威化し、`mode=edit` で対象が存在しない / `mode=create` で重複 ID は flash 拒否。 |
| V21 | 本書を v5.5 化（冒頭メタ・現在のステータス・§8.2 受け入れ ✅ 化・本 §11）。 |
| V22 | `tests/` を新設（`conftest.py`, `test_auth.py`, `test_manage_users.py`, `test_security.py`, `test_db.py`, `test_config.py`, `test_shift_input.py`）。`requirements-dev.txt` を追加、README に `pytest` 実行手順。 |
| V23 | `init_db()` で `users.must_change_password INTEGER DEFAULT 0` を冪等 ALTER。初期 admin は `must_change_password=1`、`manage_users` で管理者がパスワードを設定した新規・既存ユーザーも `must_change_password=1`。`load_current_user` で `g.user.must_change_password` を取れるようにし、`force_password_change` before_request で `change_password / logout / static / help_page` 以外を `/change_password` へ強制リダイレクト。変更成功で `0` に戻す + `session.clear()` で再ログイン。 |
| V24 | README のコマンドを `python3 -m pip install -r ...` / `python3 app.py` に変更。Windows 等で `python` を使う場合の注記も追加。 |

### 11.3 検証

`python3 -m pytest` 全 39 件グリーン（v5.5 時点）。内訳：

- `tests/test_auth.py`（12 件）— ログイン、V1、V11、V8、V23、change_password 各検証
- `tests/test_manage_users.py`（10 件）— V19、V20、C#5/6/7、must_change_password セット
- `tests/test_security.py`（6 件）— V9、V2、N（職員→/admin 403）、Q（停止セッション無効化）、O（month=13）
- `tests/test_db.py`（4 件）— WAL PRAGMA、V23 列存在、初期 admin フラグ、冪等性
- `tests/test_config.py`（3 件）— B（SECRET_KEY 必須）、S（絶対パス必須）、C#11（TRUSTED_PROXY_HOPS）
- `tests/test_shift_input.py`（4 件）— V4、シフト保存、O

### 11.4 残作業（試用後）

§7 フェーズ2 後半 / フェーズ3 に予定どおり持ち越し:

- V12 — inline `onclick` 撤廃（worker.html / index.html 備考モーダル）
- V13〜V18 — パスワードルール強化、404/403/500 ページ、`safe_ym` 無音 fallback の警告化、等
- V25 — `index.html` と `worker.html` の Jinja `include` 共通化
- §4① 希望／確定シフト分離 + `user_id` 化（J の根本対応）
- §4②③④⑤⑥ — 提出状況ダッシュボード、パスワード再発行ワークフロー、監査ログ、開室曜日設定化、CSV/印刷出力

### 11.5 試用開始までの残ステップ

- [ ] フェーズ2.5 ブランチを PR 化 → レビュー → main マージ
- [ ] 実機（スマホ + ブラウザ）で §8.1 / §8.2 を目視確認
- [ ] サーバーで V6（admin 初期パスワード）と V7（パーミッション）を README どおり実施
- [ ] バックアップ復元演習（`sqlite3 .backup` → 削除 → 復元）を 1 度実施
- [ ] 職員 3〜5 名 + 管理者へ `/help` ページを共有
- [ ] 試用開始
