# Shift-Flow 統合コードレビュー

最終更新: 2026-06-23
対象: 現在の作業ツリー / Render Starter / SQLite / 約10名

## 結論

前回レビューで高・中優先度としたコード上の課題は実装済みです。重大または高危険度の既知脆弱性は確認されていません。

本運用移行の判定は**条件付きGo**です。コード上のゲートは通過していますが、外部保管バックアップからの復元リハーサルと実端末確認は運用開始前に必要です。

## 実装済み

### データ保全

- DB初期化をimport時から初回準備処理へ移動
- スキーマ変更前バックアップを作成
- 日次14個・月次12個・手動バックアップを分離
- 全バックアップでSQLite `integrity_check` を実行
- バックアップを同時実行ロックと一時ファイルの原子的置換で保護
- 最終成功・失敗をDBへ記録し、管理メニューへ警告
- ディスク空き10%未満を管理メニューへ警告
- `/healthz` とDB確認付き `/readyz` を分離

### 認証・設定

- 新規・変更パスフレーズを15〜128文字へ変更
- ローカル拒否リスト、ID一致拒否、Unicode NFC正規化を追加
- 既存利用者は移行後の次回ログインで新方針へ変更
- 無操作30分に加えて24時間の総セッション期限を追加
- 総期限の時刻が壊れているセッションは安全側で破棄
- GETログアウトを廃止し、CSRF保護されたPOSTへ変更
- 本番初期admin設定と全主要環境変数をfail-fast化
- 監査ログ障害時も認証・認可の本処理を安全に継続

### UI/UX・アクセシビリティ

- スマートフォンでは開室日だけを縦リスト表示
- 〇×・備考を44px以上の操作領域に変更
- ラジオ入力をキーボード操作可能なvisually-hidden方式へ変更
- 全フォームに明示的なラベルを設定
- `:focus-visible`、ライブ通知、モーダルのEsc・フォーカス循環・復帰を追加
- 備考へ500文字制限、残文字数、機微情報の注意を表示
- 保存後の標準`confirm()`と備考表示の`alert()`を廃止
- 管理メニューを「今日使う」「確定する」「管理・確認」へ整理
- 操作ログの表示時刻をJSTへ変更

### 軽量化・保守性

- 管理者用・職員用の重複入力テンプレートを統合
- 403/404/413/500を共通エラーテンプレートへ統合
- 全画面のHTML骨格を `base.html` へ統合
- 月切替と戻る導線をJinjaマクロへ統合
- inline styleを撤去し、CSPの `style-src 'unsafe-inline'` を撤去
- 設定、DB、パスワード、時刻処理を独立モジュールへ分離
- 空の `tests/__init__.py` と未使用importを削除
- 正規の職員入力URLを `/worker` に変更し、旧氏名URLは互換リダイレクト

## 検証結果

| 検証 | 結果 |
|---|---|
| `PYTHONWARNINGS=error python3 -m pytest -q` | **120 passed（警告なし）** |
| `python3 -m py_compile ...` | 成功 |
| `python3 -m pip check` | 依存関係の破損なし |
| `python3 -m pip_audit -r requirements.txt` | 既知脆弱性なし |
| `git diff --check` | 問題なし |
| 実ブラウザ（390px） | 横はみ出しなし、44px未満の操作部品なし、コンソール警告なし |

自動テストには、移行前バックアップ、日次・月次保持、バックアップ競合、JST月境界、パスフレーズ方針、設定不正値、壊れた総セッション期限、監査ログ障害、POSTログアウト、`/readyz`、備考上限を含みます。

## 残存リスク

### 運用で対応

- 同一ディスク内バックアップはディスク全損に耐えないため、月次で外部保存する
- 復元手順は本番データではなく複製DBで定期的に練習する
- 備考へ相談内容・健康情報・個人情報を書かない

### 小規模運用として受容

- レート制限は単一workerのメモリ内。複数worker化時はRedisへ移行する
- MFAは未実装。機微情報を扱う運用へ変わる場合は再評価する
- 頻出パスフレーズの拒否リストは小規模なローカル判定。外部漏えいDBとの完全照合ではない
- ルート処理は主に `app.py` に残る。現規模では動作の追跡容易性を優先し、過度なBlueprint分割は保留する
- 依存は既知脆弱性がない範囲で固定し、メジャー更新を一括適用しない

## 一次資料

- [NIST SP 800-63B](https://pages.nist.gov/800-63-4/sp800-63b.html)
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)
- [OWASP ASVS 5.0](https://owasp.org/www-project-application-security-verification-standard/)
- [Flask Security Considerations](https://flask.palletsprojects.com/en/stable/web-security/)
- [SQLite Online Backup API](https://www.sqlite.org/backup.html)
- [Render Persistent Disks](https://render.com/docs/disks)
- [GHSA-68rp-wp8r-4726](https://github.com/advisories/GHSA-68rp-wp8r-4726)
- [GHSA-hgf8-39gv-g3f2](https://github.com/advisories/GHSA-hgf8-39gv-g3f2)

## リリース前チェック

- [ ] Renderのヘルスチェックが `/readyz`
- [ ] 初回移行で `pre-migration-*.db` が作成されている
- [ ] 日次・月次バックアップが `integrity_check=ok`
- [ ] 月次バックアップを手元へ保存した
- [ ] 外部保存ファイルから復元リハーサルを実施した
- [ ] 既存利用者へ次回パスフレーズ変更を案内した
- [ ] 管理者・職員の実スマートフォンで主要操作を確認した
- [ ] `/logs` のIPが利用者単位で妥当
