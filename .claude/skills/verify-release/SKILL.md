---
name: verify-release
description: Shift-Flow のリリース前検証一式（テスト・コンパイル・依存整合・差分チェック）を実行し、合否を表で報告する。コード変更後・PR作成前・「検証して」「リリース前確認」と言われたときに使う。
---

# リリース前検証

リポジトリのルートで以下を**順に**実行し、結果を表（項目／結果／備考)で報告する。

1. `PYTHONWARNINGS=error python3 -m pytest -q -p no:cacheprovider`
   - 全件パスが条件（2026-07 時点の基準は 151 件。テストを増減させた変更なら PR に件数の増減理由を書く）
2. `python3 -m py_compile app.py settings.py storage.py security_utils.py time_utils.py`
3. `python3 -m pip check`
4. `git diff --check`
5. 依存（requirements*.txt）を変更した場合のみ: `python3 -m pip_audit -r requirements.txt`

追加ルール:

- UI（templates/・static/）を変更した場合は、プレビューで実画面（モバイル 375px）を確認し、スクリーンショットか確認内容を報告に含める。
- **1つでも失敗したら「合格」と報告しない。** 失敗内容を示し、修正 → 再実行してから報告する。
- 検証コマンド自体を弱めない（`PYTHONWARNINGS=error` を外す等は禁止）。
