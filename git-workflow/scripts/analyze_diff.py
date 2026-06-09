#!/usr/bin/env python3
"""
Git差分を分析してClaudeが解釈しやすい構造化JSONを出力するスクリプト。

使い方:
  python .claude/skills/git-workflow/scripts/analyze_diff.py

出力:
  {
    "status": "ok",
    "branch": "main",
    "last_commit": "abc1234 feat: ...",
    "changed_files": [...],
    "file_count": 3,
    "stats": { "working_tree": "...", "staged": "..." },
    "diff": "..."
  }
"""
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

MAX_DIFF_LINES = 600  # 長すぎる差分は切り詰める


def run_git(args: list[str]) -> tuple[str, int]:
    """gitコマンドを実行して (stdout, returncode) を返す。"""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip(), result.returncode


def get_changed_files() -> list[dict]:
    """変更ファイルの一覧と状態を取得する。"""
    output, _ = run_git(["status", "--porcelain"])
    files = []
    for line in output.splitlines():
        if not line.strip():
            continue
        staged_status = line[0]
        unstaged_status = line[1]
        filename = line[3:].strip()
        # リネームの場合は "old -> new" 形式になるので新ファイル名だけ取る
        if " -> " in filename:
            filename = filename.split(" -> ")[-1]
        files.append({
            "path": filename,
            "staged": staged_status.strip() or None,
            "unstaged": unstaged_status.strip() or None,
            "extension": Path(filename).suffix.lstrip(".") or "none",
        })
    return files


def get_diff_content(max_lines: int = MAX_DIFF_LINES) -> str:
    """差分の内容を取得する（大きすぎる場合は切り詰める）。"""
    # まずHEADとの差分を試みる（コミット済みがある場合）
    diff, rc = run_git(["diff", "HEAD"])
    if rc != 0 or not diff:
        # HEADがない（初回コミット前）場合はステージ済み差分を取得
        diff, _ = run_git(["diff", "--staged"])
    if not diff:
        # ステージされていない変更のみ
        diff, _ = run_git(["diff"])

    lines = diff.splitlines()
    if len(lines) > max_lines:
        truncated = "\n".join(lines[:max_lines])
        return truncated + f"\n\n... (残り {len(lines) - max_lines} 行は省略されました)"
    return diff


def main():
    # gitリポジトリかどうか確認
    _, rc = run_git(["rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        print(json.dumps({
            "status": "error",
            "message": "Gitリポジトリが見つかりません。`git init` でリポジトリを初期化してください。"
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        files = get_changed_files()
        diff_content = get_diff_content()

        branch, _ = run_git(["branch", "--show-current"])
        last_commit, rc = run_git(["log", "--oneline", "-1"])
        if rc != 0:
            last_commit = "(まだコミットがありません)"

        stat_working, _ = run_git(["diff", "HEAD", "--stat"])
        stat_staged, _ = run_git(["diff", "--staged", "--stat"])

        output = {
            "status": "ok",
            "branch": branch or "（ブランチ名なし）",
            "last_commit": last_commit,
            "changed_files": files,
            "file_count": len(files),
            "stats": {
                "working_tree": stat_working or "（変更なし）",
                "staged": stat_staged or "（ステージなし）",
            },
            "diff": diff_content or "（差分なし）",
        }
    except Exception as e:
        output = {
            "status": "error",
            "message": str(e),
        }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
