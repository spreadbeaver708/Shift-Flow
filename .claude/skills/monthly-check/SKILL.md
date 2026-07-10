---
name: monthly-check
description: Shift-Flow の月次点検。自動チェック（pip-audit・更新可能な依存・テスト）を実行し、手動チェック（/logs・バックアップ・外部保存・JST）の確認票を提示する。「月次点検」「monthly check」「毎月の確認」と言われたときに使う。
---

# 月次点検

## 1. 自動チェック（実行して結果を報告）

```bash
python3 -m pip_audit -r requirements.txt        # 既知脆弱性ゼロが合格
python3 -m pip list --outdated                  # 参考情報（即更新はしない。下記ルール参照）
PYTHONWARNINGS=error python3 -m pytest -q -p no:cacheprovider   # 全件パス
```

依存の更新ルール: **pip-audit が脆弱性を報告したパッケージだけ**を最小の範囲で更新し、
requirements.txt のピンとコメント（CVE 記録）を更新 → `/verify-release` で全検証 → PR。
outdated なだけのものは更新しない（CLAUDE.md 設計判断 9）。

## 2. 手動チェック（運用者に確認票として提示）

以下を運用者が本番画面で確認する（README「毎月の確認」と同じ内容）:

- [ ] `/logs` に不審なログイン失敗・権限エラーがない（多発があれば docs/WORK_ORDERS.md の WO-05 検討の入口）
- [ ] 管理メニューの「バックアップ」欄に失敗警告がない
- [ ] 最新バックアップが新しく、`integrity_check` が `ok`
- [ ] 月次バックアップ（monthly-*.db）を手元へ保存し、「外部保存を確認した」を押した
- [ ] 本番の「今月」表示が日本時間と一致している

## 3. 記録

結果に問題があれば docs/ROADMAP.md の該当項目へ反映し、必要なら新しい WO を docs/WORK_ORDERS.md に追記する。
