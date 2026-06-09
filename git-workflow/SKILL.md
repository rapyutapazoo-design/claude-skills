---
name: git-workflow
description: Use this skill for code review AND git commit/push operations. Auto-triggers on review requests like "レビューして", "コードを確認して", "変更を見て", "差分を教えて", "review my code", "check changes". Also activates when the user wants to commit or push: "コミットして", "プッシュして", "GitHubにあげて", "変更を保存して". When pushing, this skill ALWAYS runs a code review first and requires explicit user approval before executing any git write operation. This is the only permitted path for push in this project.
disable-model-invocation: false
---

# Git Workflow Skill

コードレビューと、レビュー承認後のコミット・プッシュを一貫して担うスキル。

**2つのモード:**
- **モードA（レビューのみ）**: 差分を分析してフィードバックを提供する。プッシュはしない。
- **モードB（レビュー → 承認 → プッシュ）**: 必ずレビューを先に実施し、ユーザーの明示的な承認を得てからコミット・プッシュを実行する。

> **原則**: プッシュはこのスキル内のフローでのみ実行する。スキル外からの直接実行は禁止されている。

---

## モードの判断

ユーザーの発言から意図を読み取り、モードを選択する:

| ユーザーの発言例 | モード |
|----------------|--------|
| 「レビューして」「変更を確認して」「差分を見て」 | **A: レビューのみ** |
| 「コミットして」「プッシュして」「GitHubにあげて」 | **B: レビュー → 承認 → プッシュ** |
| `/git-workflow` のみ（意図不明） | ユーザーに「レビューだけ？それともプッシュまで？」と確認してからモードを決める |

---

## モードA: レビューのみ

### A-1. 変更内容を分析する

```
python .claude/skills/git-workflow/scripts/analyze_diff.py
```

結果の処理:
- `status: error` → エラー内容を伝え、`git init` を提案して終了する
- `file_count: 0` → 「レビューする変更がありません」と伝えて終了する
- `status: ok` → 次へ進む

### A-2. コーディング規約を参照する

`.claude/skills/git-workflow/references/coding_standards.md` を読み込み、プロジェクトの規約を把握する。

### A-3. 差分をレビューする

差分と規約を照合し、以下の観点で評価する:

- **型安全性**: `any` 使用・型の明示不足・非nullアサーション (`!`) の誤用
- **React/Next.js パターン**: Server/Client Components の使い分け、hooksのルール、コンポーネント設計
- **命名・構成**: 命名規則・ファイル配置・インポート順序
- **エラーハンドリング**: 外部API呼び出しの `try/catch`、エラー境界
- **パフォーマンス**: 不要な再レンダリング、クライアントで動くべきでない重い処理

### A-4. レビュー結果を出力する

`.claude/skills/git-workflow/assets/review_template.md` のフォーマットで結果を出力する。

重要度の表記:
- 🔴 **要修正**: バグ・規約違反など必ず直すべき問題
- 🟡 **推奨**: 品質向上のための提案
- 🟢 **良い点**: 良い実装を積極的に評価する（省略しないこと）

### A-5. 次のアクションを提案する

- 🔴 要修正がある場合 → 具体的な修正コードを示す
- 問題なし or 🟡のみ → 「問題なければ `/git-workflow` でプッシュまで進められます」と案内する

---

## モードB: レビュー → 承認 → プッシュ

**プッシュは必ずレビューの後。承認なしには絶対に実行しない。**

### B-1〜B-4. レビューを実施する

モードAの **A-1〜A-4 と同じ手順** でレビューを実施し、結果を出力する。

### B-5. 承認を求める（ゲート）

レビュー結果を提示した後、**必ずユーザーに確認する**:

> 「レビュー結果を確認しました。このままコミット・プッシュを進めてよいですか？」

応答に応じた分岐:

| ユーザーの応答 | 動作 |
|--------------|------|
| 「はい」「OK」「問題ない」「進めて」 | B-6 へ進む |
| 「いいえ」「修正する」「待って」 | **ここで終了。プッシュしない。** 修正のサポートを申し出る |
| 🔴 要修正がある状態で「進めて」 | 「要修正の問題が残っています。修正してからプッシュすることを推奨します。それでも続けますか？」と再確認する |

### B-6. コミット対象を確認する

> 「どのファイルをコミットしますか？」
> - 「全部」または `all` → 変更ファイルをすべてステージング
> - ファイルパス指定 → 指定ファイルのみ

以下は **絶対にコミットしない**:
- `node_modules/`、`.next/`、`.env`、`.env.local`、`*.log`、`.DS_Store`

`git add .` を使う前に `.gitignore` の内容を確認すること。

### B-7. コミットメッセージを生成する

差分の内容から変更の本質を読み取り、**Conventional Commits** 形式のメッセージを提案する:

```
<type>(<scope>): <日本語サマリー（50文字以内）>

[任意: 変更の詳細・背景]
```

**type の選択基準:**

| type | 使い所 |
|------|--------|
| `feat` | 新機能追加 |
| `fix` | バグ修正 |
| `refactor` | リファクタリング（動作変更なし） |
| `style` | フォーマット変更（ロジック変更なし） |
| `docs` | ドキュメント・コメントの変更 |
| `chore` | ビルド設定・依存関係 |
| `perf` | パフォーマンス改善 |
| `test` | テストの追加・修正 |

**scope** はモジュール名（例: `spots`, `scoring`, `weather`, `ui`）。省略可。

ユーザーに確認: 「このメッセージでよいですか？」修正を求められたら直して再確認する。

### B-8. ステージング・コミット・プッシュを実行する

```bash
git add <対象ファイルまたは .>
git commit -m "<承認されたコミットメッセージ>"
git push origin <現在のブランチ名>
```

初回プッシュ（リモートブランチが存在しない場合）:
```bash
git push --set-upstream origin <ブランチ名>
```

### B-9. 完了を報告する

コミットハッシュとメッセージを表示して完了を伝える。

必要に応じて提案する:
- PR作成が必要な場合 → `gh pr create` を案内する
- CI/CDが設定されている場合 → GitHub Actions の確認を促す

---

## エラーハンドリング

| エラー | 対処法 |
|------|--------|
| Gitリポジトリなし | `git init` を提案し、その後 `git remote add origin <URL>` を案内する |
| リモートなし | `git remote add origin <GitHub URL>` の設定を促す |
| Push rejected | `git pull --rebase origin <ブランチ名>` 後に再プッシュを提案する |
| 認証エラー | SSH鍵の設定または `gh auth login` を案内する |
| マージコンフリクト | `git status` でコンフリクトファイルを確認し、解消方法を説明する |
