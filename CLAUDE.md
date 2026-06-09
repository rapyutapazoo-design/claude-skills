# Claude への指示書 — git-workflow スキル

このフォルダ（`claude skills/`）にはClaude用のスキルが格納されています。

---

## ⚠️ Git 書き込み操作のルール（最重要）

このプロジェクトおよびスキルを使用する際、**`git commit`・`git push` などの書き込み操作は `git-workflow` スキルのフロー経由でのみ実行すること。**

スキル外からの直接実行は禁止:

```
git add
git commit
git push
git push --force
git merge
git rebase
git reset --hard
gh pr create
```

読み取り専用のgit操作は制限なし（`git status`、`git log`、`git diff` など）。

ユーザーが直接実行を求めた場合は、`/git-workflow` を使うよう案内すること。

---

## スキル一覧

### safe-push

**場所**: `safe-push/`

「安全確認してプッシュ」「セキュリティチェックしてプッシュ」などをトリガーに起動するセキュリティレビュー付きプッシュスキル。シークレット漏洩・除外ファイル混入・デバッグ文残留を自動検出し、問題がなければそのままコミット・プッシュまで完結する。

```
safe-push/
├── SKILL.md                          # スキル定義・フロー手順
├── references/security_rules.md     # セキュリティチェックルール定義
├── scripts/check_secrets.py         # シークレット・除外ファイル自動検出スクリプト
└── assets/review_template.md        # レビュー結果の出力テンプレート
```

---

### consultant-mode

**場所**: `consultant-mode/`

「検討」「検討してください」をトリガーに起動するコンサルタントモードスキル。コードや環境に一切触れず、アイデア・設計案をテキストのみで提示する。「実装してください」などのフレーズを検知するまでモードが継続する。

```
consultant-mode/
├── SKILL.md                              # スキル定義・フロー手順
└── references/release_triggers.md       # モード解除トリガーのフレーズリスト
```

---

### plan-creator

**場所**: `plan-creator/`

「計画書を作成してください」をトリガーに起動する実装計画書生成スキル。直前のコンサルタントモードで採用された案を会話履歴から自動抽出し、実装計画書をテキストで生成する。コードの書き込みは行わない。

```
plan-creator/
└── SKILL.md                              # スキル定義・フロー手順
```

---

### git-workflow

**場所**: `git-workflow/`

コードレビューとコミット・プッシュを一貫して行うスキル。

- **レビューのみ**: 「レビューして」「変更を確認して」などで自動起動
- **レビュー → 承認 → プッシュ**: 「コミットして」「プッシュして」などで自動起動。必ずレビューを先に実施し、ユーザーの承認を得てからプッシュを実行する

```
git-workflow/
├── SKILL.md                        # スキル定義・フロー手順
├── scripts/analyze_diff.py         # git diff を構造化JSONで出力
├── references/coding_standards.md  # プロジェクトのコーディング規約
└── assets/review_template.md       # レビュー結果の出力テンプレート
```
