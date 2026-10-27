# 引き継ぎファイル（handoff）形式

consultant-mode の採用案と plan-creator の計画書を、別セッションの auto-flow に引き継ぐための共通形式。
consultant-mode・plan-creator（書き込み側）と auto-flow（読み取り側）は、すべてこのファイルの定義に従う。

## 保存先

```
~/.claude/handoff/<repo-key>/<YYYYMMDD-HHMMSS>-<slug>.md
```

- 作業ツリーの外に置く（auto-flow [0] の未コミット変更チェックと衝突させないため。git にも入らない）
- **書き込みは新規作成のみ**。既存ファイルの上書き・削除はしない（例外: auto-flow による `status` の consumed 更新）
- 日時は UTC（`date -u +%Y%m%d-%H%M%S`）。slug は話題由来の英小文字・数字・ハイフン、最大30文字
- 同名ファイルが既にあれば slug 末尾に `-2`, `-3` … を付ける

### repo-key

1. `git rev-parse --show-toplevel` の絶対パスを取る（失敗したら repo 外 → `_unscoped`）
2. 先頭の `/` を除き、残りの `/` を `-` に、空白を `_` に置き換える

例: `/Users/me/Projects/my app` → `Users-me-Projects-my_app`

## ファイル形式

```markdown
---
kind: design            # design = 採用案（consultant-mode） / plan = 計画書（plan-creator）
status: adopted         # adopted = 未使用 / consumed = auto-flow で使用済み
topic: <話題の1行要約>
repo: <git toplevel の絶対パス または null>
base_sha: <保存時の HEAD または null>
source: consultant-mode # consultant-mode / plan-creator
adopted_option: <採用した案の名前（例: 案B）>
adoption_quote: "<採用根拠となったユーザー発話の原文引用>"
design_ref: null        # plan のみ: 元にした design ファイル名（あれば）
created_at: <YYYY-MM-DDTHH:MM:SSZ>
consumed_by: null       # consumed 時に auto-flow の実行ID
---

（kind: design → 採用案を含む4セクションの最終版全文。複数回の再検討を経た場合は最新版に統合し、採用案を「3. 推奨案」に置く）
（kind: plan → 計画書全文）
```

## 取り扱い上の注意

- 平文で保存される。秘密情報（APIキー・パスワード・個人情報）は本文に書かない。含まれる話題ではファイルを作らず、保存しなかった旨を1行伝える
- auto-flow は `status: adopted` かつ `created_at` から14日以内のものだけを引き継ぎ候補にする
- 不要になったファイルはユーザーが手動で削除してよい
