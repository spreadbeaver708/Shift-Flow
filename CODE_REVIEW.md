# Shift-Flow コードレビュー報告書

- **対象**: カウンセリングルーム シフト管理アプリ（Flask製）
- **構成**: `app.py`(196行) / `templates/*`(8ファイル) / `static/style.css` / `requirements.txt`
- **想定運用**: **インターネット公開**。各スタッフがスマホからシフト希望を入力、管理者が集計・調整。
- **レビュー履歴**:
  - 初版 2026-05-28（Claude Code）
  - v2 2026-05-28 — Codex作成の外部計画書と統合、運用方針を確定
  - v3 2026-05-28 — Codexからの再評価を反映（P/Q/R/S 追加、ロードマップ再構成、`fillForm` 例修正）
  - v4 2026-05-28 — 希望/確定の閲覧モデル明確化、SQLite例の単一化、Cookieは本番限定
  - v4.1 2026-05-28 — Codex 最終評価を反映（フェーズ1閲覧条件補正、`SECRET_KEY` fail-fast、`FLASK_ENV` → `APP_ENV`）
  - **v4.2 2026-05-28 — 最終確定版**（Codex フォローアップを反映：テンプレを `current_user` に統一、**S を 🟡 中に格上げしフェーズ1へ**、login 例に `session.clear()`）
- **環境**: Python 3.14.2 / Flask 3.1.0
- **本レビューの範囲**: 報告のみ（本体コードは未変更）。重大・高リスク項目は実機で再現確認済み。
- **本書のステータス**: **実装前チェックリスト（最終確定版）**。フェーズ1着手前に §7 の手順で取りかかる。

> ⚠️ **結論を先に**: 現状のままインターネット公開すると、**全パスワード漏洩**・**なりすまし**・
> **管理者画面での任意スクリプト実行**・**職員による全同僚の備考閲覧**・**停止/降格後も旧セッションで
> 管理画面アクセス可能**といった事象が現実的に起こり得ます。
> §7「フェーズ1（試用開始の前提）」が **そろうまでは公開しないでください**。

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

| # | 重大度 | 項目 | 該当箇所 | 推奨対応 |
|---|--------|------|----------|----------|
| A | 🔴 重大 | パスワード平文保存＋ブラウザへ平文送信 | `app.py:23,30,65,154` / `manage_users.html:33` | ハッシュ化、編集時はパスワード非送信 |
| B | 🔴 重大 | `secret_key` ハードコード（git commit済み） | `app.py:8` | 環境変数化＋ローテーション |
| C | 🔴 重大 | 既知の初期 `admin` / `admin123` | `app.py:30` | 環境変数で初期化、初回強制変更 |
| D | 🟠 高 | CSRF対策が皆無（全POST） | `app.py:60-188` | Flask-WTF の CSRFProtect |
| E | 🟠 高 | 備考の保存型XSS＋改行で機能破損 | `admin.html:29` | onclick への埋め込み廃止／可能なら addEventListener |
| N | 🟠 高 | 職員が全員のシフト・備考を閲覧可（認可・プライバシー） | `app.py:128` / `menu.html:28` / `admin.html:27-31` | フェーズ1: `/admin` を管理者専用（職員メニューからリンク削除）。全体〇× 公開はフェーズ3 確定シフトと同時 |
| F | 🟠 高 | `REPLACE INTO` による停止解除・重複バグ | `app.py:154` | UPDATE/INSERT 明示分岐、is_active 維持 |
| **Q** | 🟠 高 | **停止/降格後も旧セッションで管理画面に到達可（実機確認済）** | `app.py:75,118,123,128,143` | リクエスト毎にDBからユーザー状態を再取得して認可判定 |
| G | 🟡 中 | 本番で `debug=True` 相当の危険 | `app.py:196` | gunicorn運用・debug禁止 |
| H | 🟡 中 | セッションCookie属性が未設定 | `app.py`(全体) | Secure/HttpOnly/SameSite |
| I | 🟡 中 | ログイン試行回数の制限なし | `app.py:60` | Flask-Limiter で簡易レート制限 |
| J | 🟡 中 | シフトを表示名で管理（同名衝突） | `app.py:92,110,133` | **直接 `user_id` 基準へ**（§4① と一体実装） |
| O | 🟡 中 | 範囲外 year/month で500クラッシュ | `app.py:88,129,139` | 範囲・値の検証 |
| **P** | 🟡 中 | **ログイン時に旧セッションを破棄していない** | `app.py:67-68` | `session.clear()` してから新セッションを設定 |
| K | 🟢 低 | `change_password` が未ログインで実行可 | `app.py:174-188` | 仕様確認・情報露出注意 |
| L | 🟢 低 | `result.html` 未使用・起動毎 DELETE | `result.html` / `app.py:33` | 削除・副作用の認識 |
| M | 🟢 低 | 依存バージョン未固定 | `requirements.txt` | バージョンピン留め |
| **R** | 🟢 低 | **SQLite 同時書き込み堅牢化未対応** | `app.py:14` | `timeout` 指定／WAL／明示トランザクション |
| **S** | 🟡 中 | **`shift.db` パスが CWD 依存の相対固定**（gunicorn 起動場所違いで別DBを作る事故） | `app.py:14` | 環境変数 `SHIFT_DB_PATH` or `app.instance_path` 配下へ（v4.2でフェーズ1へ昇格） |

太字は**後続レビューで追加・昇格した項目**です（v3 で追加: P/Q/R/S、v4.2 で S を 🟢→🟡 へ昇格）。Codex の各回再評価指摘を全件取り込みました。

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

### フェーズ2：試用初期に並行で進める堅牢化（試用開始後 1〜2 週間）
15. **L** `result.html` 削除・起動時 DELETE を分離
16. **M** 依存バージョン固定（Flask, gunicorn, Flask-WTF, Flask-Limiter, python-dotenv）
17. **R** SQLite 堅牢化（`timeout` / WAL / 明示TX）
18. **K** `change_password` の仕様整理（レート制限と合わせて運用判断）
19. inline `onclick` の全廃→`addEventListener`（CSP導入の前準備）

> v4.2 修正: **S はフェーズ1 に移動**（gunicorn 起動と同時に効く事故防止のため）。

### フェーズ3：本格運用機能（試用結果を踏まえて 1〜2 か月）
20. **§4①** 希望提出／確定シフトの分離（同時に **J** を `user_id` 化、**確定シフト画面で全員の〇× を職員にも公開**）
21. **§4②** 提出状況ダッシュボード（未提出者・締め日・締め後ロック）
22. **§4③** パスワード再発行（管理者→初回変更）
23. **§4④** 監査ログ
24. **§4⑤⑥** 開室曜日の設定化／CSV出力（任意）

### フェーズ4：長期運用の保守性
25. README 化（環境変数・gunicorn・HTTPS・バックアップ/復元手順）
26. SQLite 日次バックアップ＋管理者ダウンロード導線
27. デザインの保守改善（インライン style 集約・worker/index 重複の共通テンプレ化・暗色カラーの文字色自動調整）
28. 監査ログのローテーション・容量監視

---

## 8. 受け入れテスト（試用開始の合格基準）

フェーズ1 を完了した時点で、以下がすべて緑であること。

**🔴 重大・🟠 高**
- [ ] 固定 `secret_key` と `admin123` がコードに存在しない（A/B/C）
- [ ] パスワードが DB にも HTML にも平文で出ない（A）
- [ ] CSRFトークン無しの POST が拒否される（D）
- [ ] 悪意ある備考（`'`・改行・`<script>`）で管理者画面にスクリプト実行されない（E）
- [ ] **職員は `/admin` にアクセスできない**（フェーズ1では管理者専用／N）
- [ ] **職員メニューに「全体のシフト確認」リンクが表示されない**（N）
- [ ] 職員は `/manage_users` にアクセスできない（既存保護を維持）
- [ ] **停止した職員の旧セッションから `/menu` `/worker` にアクセスできない**（Q）
- [ ] **worker に降格された旧 admin の旧セッションで `/manage_users` にアクセスできない**（Q）
- [ ] **降格された旧adminの旧セッションでメニューに管理者向けリンクが表示されない**（Q／テンプレも `current_user` 経由＝v4.2）
- [ ] 停止ユーザーを編集しても勝手に復活しない（F）

**🟡 中**
- [ ] `month=13` や欠落フォームで 500 にならない（O）
- [ ] ログインに `/login` 連打すると一定回数で 429 が返る（I）
- [ ] ログイン直後の session に前ユーザーの値が残らない（P）
- [ ] `debug` が無効、本番は gunicorn 起動（G/H）
- [ ] **DB ファイルが `SHIFT_DB_PATH` 等で固定された絶対パスに置かれ、CWD 違いで別 DB が作られない**（S／v4.2 でフェーズ1 へ）

**🟢 低 / フェーズ2 以降**
- [ ] `templates/result.html` が存在しない（L）
- [ ] 依存が `requirements.txt` でピン留め済（M）
- [ ] 同時多発書き込みで「database is locked」が出ない（R）

**フェーズ3 完了時**
- [ ] 同名職員を作っても希望/確定が混線しない（J→`user_id` 化）
- [ ] 管理者が提出状況を確認し、確定シフトを保存できる（§4①②）
- [ ] 職員は **他人の希望にアクセスできない**（希望は自分のみ）（§4①）
- [ ] 職員は **確定の全体〇×** を閲覧できる（公的シフト表として共有）（§4①）
- [ ] 確定シフトには備考列が存在しない／表示されない（§4①）
- [ ] 管理者がパスワード再発行できる（§4③）
- [ ] 主要操作が監査ログに記録される（§4④）

---

### 付記：本レビューの検証方法・履歴
- Flask の `test_client` で実際のログイン〜操作フローを再現し、**A／E／F／N／O／Q** を実機確認した
  （本体コードは変更せず、検証用 DB は破棄）。
- B／C／D／G・H・I・J・K・L・M・P・R・S はコード静的解析に基づく指摘。
- 本報告書の統合履歴
  - 初版（Claude Code）→ v2（Codex 外部計画書を統合）→ v3（Codex 第2回再評価を反映）→
    v4（Codex 第3回再評価を反映＋希望/確定の閲覧モデルをユーザー再確認）→
    v4.1（Codex 最終評価を反映：フェーズ1 閲覧条件補正・`SECRET_KEY` fail-fast・`APP_ENV` 統一）→
    **v4.2 最終確定版（Codex フォローアップを反映：テンプレを `current_user` に統一・S をフェーズ1 へ昇格・login 例に `session.clear()`）**
- 以降、実装フェーズ1 を着手する際は本書 §7・§8 を参照する。
- **運用**: `CODE_REVIEW.md` は実装着手前に **レビュー記録としてコミット対象** とする
  （Codex 最終評価の運用指摘に対応）。
