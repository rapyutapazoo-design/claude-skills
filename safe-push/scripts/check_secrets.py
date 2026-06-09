#!/usr/bin/env python3
"""
safe-push: プッシュ前セキュリティチェックスクリプト
git diff --cached の内容を解析し、シークレット・除外ファイルを検出してJSON出力する
"""

import subprocess
import re
import json
import sys

# シークレット検出パターン
SECRET_PATTERNS = [
    {"name": "AWS Access Key",        "pattern": r"AKIA[0-9A-Z]{16}"},
    {"name": "GCP API Key",           "pattern": r"AIza[0-9A-Za-z\-_]{35}"},
    {"name": "GitHub Token",          "pattern": r"gh[posr]_[0-9a-zA-Z]{36}"},
    {"name": "Slack Token",           "pattern": r"xox[baprs]-[0-9A-Za-z\-]+"},
    {"name": "Stripe Live Key",       "pattern": r"sk_live_[0-9a-zA-Z]{24,}"},
    {"name": "DB Connection String",  "pattern": r"[a-z]+://[^:]+:[^@]+@"},
    {"name": "Generic Secret",        "pattern": r'(?i)(secret|api_key|apikey|password|passwd|token)\s*[:=]\s*["\']?[A-Za-z0-9/+_\-]{8,}["\']?'},
]

# 除外すべきファイルパターン
EXCLUDED_FILE_PATTERNS = [
    r"\.env(\.(local|production|development|staging))?$",
    r"node_modules/",
    r"\.log$",
    r"\.DS_Store$",
    r"\.(pem|key|p12|pfx)$",
    r"credentials\.json$",
    r"service[-_]account\.json$",
]

def get_staged_diff():
    """ステージされた差分を取得"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--unified=0"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, result.stderr
    return result.stdout, None

def get_staged_files():
    """ステージされたファイル一覧を取得"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return [], result.stderr
    return result.stdout.strip().splitlines(), None

def check_secrets(diff_text):
    """差分テキストからシークレットを検出"""
    findings = []
    for line_num, line in enumerate(diff_text.splitlines(), 1):
        if not line.startswith("+") or line.startswith("+++"):
            continue  # 追加行のみチェック
        for pat in SECRET_PATTERNS:
            if re.search(pat["pattern"], line):
                findings.append({
                    "type": pat["name"],
                    "line": line_num,
                    "content": line[:120]  # 長すぎる場合は切り詰め
                })
    return findings

def check_excluded_files(staged_files):
    """除外すべきファイルが含まれていないか確認"""
    findings = []
    for f in staged_files:
        for pat in EXCLUDED_FILE_PATTERNS:
            if re.search(pat, f):
                findings.append({"file": f, "reason": pat})
                break
    return findings

def check_debug_statements(diff_text):
    """デバッグ文の残留チェック"""
    debug_patterns = [
        r"\bconsole\.log\b",
        r"\bprint\s*\(",
        r"\bdebugger\b",
        r"\bpdb\.set_trace\b",
        r"\bbyebug\b",
        r"\bbinding\.pry\b",
    ]
    findings = []
    for line_num, line in enumerate(diff_text.splitlines(), 1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for pat in debug_patterns:
            if re.search(pat, line):
                findings.append({"line": line_num, "content": line[:120]})
                break
    return findings

def main():
    diff, err = get_staged_diff()
    if err:
        print(json.dumps({"status": "error", "message": err}))
        sys.exit(1)

    if not diff:
        print(json.dumps({"status": "no_changes", "message": "ステージされた変更がありません"}))
        sys.exit(0)

    staged_files, err = get_staged_files()
    if err:
        print(json.dumps({"status": "error", "message": err}))
        sys.exit(1)

    result = {
        "status": "ok",
        "staged_files": staged_files,
        "secrets": check_secrets(diff),
        "excluded_files": check_excluded_files(staged_files),
        "debug_statements": check_debug_statements(diff),
    }

    # 総合判定
    has_critical = bool(result["secrets"] or result["excluded_files"])
    result["has_critical"] = has_critical
    result["has_warnings"] = bool(result["debug_statements"])

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
