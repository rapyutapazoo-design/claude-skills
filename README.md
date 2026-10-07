# Claude Skills

Claude Code用のカスタムスキル集です。スキルはフォルダ単位で管理されており、それぞれが特定のタスクを自動化するための手順・スクリプト・規約を含んでいます。

## スキル一覧

### 🤔 [`consultant-mode/`](./consultant-mode/)

「検討」「検討してください」をトリガーに起動するコンサルタントモードスキル。

- コードや環境に一切触れず、アイデア・設計案をテキストのみで提示する
- 「実装してください」などのフレーズを検知するまでモードが継続する
- `plan-creator` への連携起点として機能する

**起動トリガー:** 「検討」「検討してください」

---

### 📋 [`plan-creator/`](./plan-creator/)

「計画書を作成してください」をトリガーに起動する実装計画書生成スキル。

- 直前のコンサルタントモードで採用された案を会話履歴から自動抽出
- 採用案サマリー・実装ステップ・考慮事項・完了条件の4セクションで出力
- コードの書き込みは行わない

**起動トリガー:** 「計画書を作成してください」「実装計画書を作成してください」

---

### 🔒 [`safe-push/`](./safe-push/)

プッシュ前にセキュリティ・品質チェックを自動実行し、問題がなければそのままコミット・プッシュまで完結するスキル。

- シークレット漏洩（APIキー・トークン等）の自動検出
- 除外ファイル（`.env` / `*.pem` 等）の混入チェック
- デバッグ文残留の検出
- 🔴 問題あり → プッシュブロック、🟡 注意のみ → 承認で続行

**起動トリガー:** 「安全確認してプッシュ」「セキュリティチェックしてプッシュ」「レビューしてプッシュ」

---

### 🔍 [`researcher/`](./researcher/)

「調査してください」「調べてください」「リサーチしてください」「リサーチして」をトリガーに起動するリサーチスキル。

- Web検索・ファイル読み取りなどの調査ツールを積極活用
- フェーズごとに進捗を表示（🔍 リサーチモード | フェーズN）
- 推奨案・比較表は不要。調査結果をそのまま提示し1回で完結

**起動トリガー:** 「調査してください」「調べてください」「リサーチしてください」「リサーチして」

---

### ⚙️ [`git-workflow/`](./git-workflow/)

コードレビューとコミット・プッシュを一貫して行うスキル。

- **モードA（レビューのみ）**: 差分を分析してフィードバックを提供
- **モードB（レビュー → 承認 → プッシュ）**: レビュー後にユーザーの承認を得てからプッシュ

**起動トリガー:** 「レビューして」「コミットして」「プッシュして」

---

### 🚀 [`auto-flow/`](./auto-flow/)

検討→計画→実装→独立レビュー→セキュリティチェック→マージ判定ゲートを確認なしで自律的に進め、全ゲートに合格したときだけ main へ自動マージするワークフロー・オーケストレーター。

- 動的モデル選択と短縮ルート
- G1〜G8 のマージ判定ゲート（不合格なら PR止め）
- 2層フック関所
- オプション `--research` / `--economy` / `--fable` / `--no-merge`、「auto-flow 再開」で中断地点から再開
- 成果物は `.auto-flow/<実行ID>/` に保存

**起動トリガー:** 「オートフロー」「auto-flow」「自律実行して」「自動で最後まで進めて」「全自動で進めて」、`/auto-flow <課題>`

※ auto-flow への言及・質問・検討依頼・改善依頼では起動しません。

---

## スキルの適用方法

### グローバル適用（全プロジェクトで使用）

```bash
mkdir -p ~/.claude/skills
cp -r <スキルフォルダ> ~/.claude/skills/
```

### プロジェクト単位で適用

スキルフォルダをプロジェクトの `.claude/skills/` に配置してください。

### auto-flow のセットアップ

- 前提: `python3` と `git`（PR を作る場合は `gh` も）
- 依存スキルの `researcher` / `consultant-mode` / `plan-creator` / `safe-push` も `~/.claude/skills/` に配置してください。
- **配置は必ず `~/.claude/skills/auto-flow/`** です（フックのパスが固定されているため、プロジェクト単位では配置できません）。

```bash
mkdir -p ~/.claude/skills
cp -r auto-flow ~/.claude/skills/
```

`~/.claude/settings.json` の `UserPromptSubmit` と `UserPromptExpansion` に、次のフックを登録してください（既存の hooks がある場合はマージします）。未設定だと常に PR止めになります。

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "timeout": 10,
            "command": "f=\"$HOME/.claude/skills/auto-flow/hooks/prompt_token.py\"; [ -f \"$f\" ] || exit 0; command -v python3 >/dev/null 2>&1 || exit 0; python3 \"$f\" >/dev/null 2>&1; exit 0"
          }
        ]
      }
    ],
    "UserPromptExpansion": [
      {
        "hooks": [
          {
            "type": "command",
            "timeout": 10,
            "command": "f=\"$HOME/.claude/skills/auto-flow/hooks/prompt_token.py\"; [ -f \"$f\" ] || exit 0; command -v python3 >/dev/null 2>&1 || exit 0; python3 \"$f\" >/dev/null 2>&1; exit 0"
          }
        ]
      }
    ]
  }
}
```

- `af_guard.py` は SKILL.md の frontmatter で自動登録されます。
- Git フックは `install_guards.py` が repo ごとに設置します。
- **撤去の前に、ガードを設置した全 repo で次を実行してください。**

```bash
python3 ~/.claude/skills/auto-flow/hooks/install_guards.py uninstall --repo <repo>
```

### テストの実行

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s auto-flow/hooks/tests -v
```

テストでは HOME と git 設定が隔離されます。

---

## ワークフロー

このスキル群は以下の流れで連携して使うことを想定しています:

```
検討してください（consultant-mode）
    ↓
計画書を作成してください（plan-creator）
    ↓
実装してください（通常モード）
    ↓
安全確認してプッシュ（safe-push）
```

全自動ルート（auto-flow）:

```
[1]調査(任意) → [2]検討 → [3]計画 → [4]実装 → [5]レビュー ⇄ [5']自動修正 → [6]チェック&push → [7]ゲート → [8]完了報告
```

小規模な課題では [2][3] を省略します。全ゲートに合格したときだけ main へ自動マージし、不合格なら PR止めになります。

---

*Created by rapyutapazoo-design.*
