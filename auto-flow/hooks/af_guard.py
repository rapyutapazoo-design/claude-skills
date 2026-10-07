#!/usr/bin/env python3
"""auto-flow 補助ガード（層2）: PreToolUse(Bash) フック。

Git フックで守れない `gh pr merge` と、Git フックを迂回・改変する操作だけを、
単純な部分文字列判定で拒否する（exit 2 + stderr）。実行中(state.json running)以外は常に exit 0。
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import af_common as C  # noqa: E402

WRITE_WORDS = ("rm ", "mv ", "cp ", "chmod", "ln ", "tee", ">", "sed -i", "truncate",
               "unlink", "install ")


_SEP = set(";&|()<>")
_VAL_OPTS = ("--message", "--file", "--author", "--reuse-message", "--reedit-message", "--template",
             "--date", "--fixup", "--squash", "--cleanup", "--gpg-sign")
_GLOBAL_ARG = ("-c", "-C", "--exec-path", "--git-dir", "--work-tree", "--namespace")


def _segments(c, depth=0):
    """c を git コマンド単位のトークン列に分ける。bash -c '...' の引数は再帰。失敗時は None。"""
    lex = shlex.shlex(c, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    toks = list(lex)
    segs, cur, prev = [], [], None
    for i, t in enumerate(toks):
        if t and set(t) <= _SEP:
            segs.append(cur)
            cur = []
        elif t == "git" or t.endswith("/git"):
            segs.append(cur)
            cur = ["git"]
        else:
            cur.append(t)
            if depth < 3 and prev in ("-c", "eval") and " " in t and \
                    (prev == "eval" or (cur and cur[0] in ("bash", "sh", "zsh", "dash"))):
                sub = _segments(t, depth + 1)
                if sub is None:
                    return None
                segs.extend(sub)
        prev = t
    segs.append(cur)
    return [s for s in segs if s]


def _subcommand(seg):
    """["git", ...global opts, sub, args...] -> (sub, args)。git で始まらなければ (None, [])。"""
    if not seg or seg[0] != "git":
        return None, []
    i = 1
    while i < len(seg):
        t = seg[i]
        if t in _GLOBAL_ARG:
            i += 2
        elif t.startswith("-"):
            i += 1
        else:
            return t, seg[i + 1:]
    return None, []


def _commit_no_verify(args):
    skip = False
    for t in args:
        if skip:
            skip = False
        elif t.startswith("--"):
            skip = t.split("=")[0] in _VAL_OPTS and "=" not in t
        elif re.fullmatch(r"-[A-Za-z]+", t):
            for k, ch in enumerate(t[1:]):
                if ch == "n":
                    return True
                if ch in "mFCct":
                    skip = (k == len(t) - 2)
                    break
    return False


_KEY_RE = re.compile(r"url\.[^\s=]*\.(push)?insteadof|remote\.[^\s=]*\.(url|pushurl)"
                     r"|branch\.[^\s=]*\.remote\b")
_CFG_WRITE_FLAGS = ("--unset", "--unset-all", "--add", "--replace-all", "--edit", "-e",
                    "--rename-section", "--remove-section")
_CFG_READ_FLAGS = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list")


def _remote_cfg_hit(segs):
    """-c による remote/upstream/insteadOf の注入、および git config での書き込みを検出する。"""
    msg = "remote URL / upstream / insteadOf の設定・注入は禁止です（リモート同期判定の偽装防止）"
    for seg in segs:
        if not seg or seg[0] != "git":
            continue
        sub, args = _subcommand(seg)
        i = 1
        while i < len(seg) and seg[i] != sub:
            if seg[i] == "-c" and i + 1 < len(seg) and _KEY_RE.search(seg[i + 1].split("=")[0]):
                return msg
            i += 2 if seg[i] in _GLOBAL_ARG else 1
        if sub == "config" and any(_KEY_RE.search(a) for a in args if not a.startswith("-")):
            if any(a in _CFG_READ_FLAGS for a in args):
                continue
            pos = [a for a in args if not a.startswith("-")]
            if len(pos) >= 2 or any(a in _CFG_WRITE_FLAGS for a in args):
                return msg
    return None


def git_rule_hit(c):
    """git サブコマンド単位の判定（メッセージ内の語を誤検知しない）。"""
    try:
        segs = _segments(c)
    except ValueError:
        segs = None
    if segs is None:  # 解析不能 → 粗い判定（過検知側）
        if re.search(r"\bcommit\b[^\n;&|]*\s-[a-z]*n(\s|$)", c) or "send-pack" in c \
                or re.search(r"\bremote\s+(add|set-url)\b", c) \
                or (_KEY_RE.search(c) and re.search(r"\bconfig\b|\s-c\b", c)
                    and not re.search(r"--get|--list|\s-l\b", c)):
            return "commit -n / send-pack / remote の変更はガード迂回になり得ます"
        return None
    if _remote_cfg_hit(segs):
        return _remote_cfg_hit(segs)
    for seg in segs:
        sub, args = _subcommand(seg)
        if sub == "commit" and _commit_no_verify(args):
            return "--no-verify / commit -n はフックの迂回です"
        if sub == "send-pack":
            return "git send-pack は push フックを迂回します"
        if sub == "remote" and args and args[0] in ("add", "set-url", "rename", "remove", "rm"):
            return "実行中の remote の追加・変更は禁止です（リモート同期判定の偽装防止）"
    return None


def rule_hit(c):
    """R2〜R7。該当すれば理由、無ければ None。c は小文字化済みコマンド。"""
    if "--no-verify" in c:
        return "--no-verify / commit -n はフックの迂回です"
    hit = git_rule_hit(c)
    if hit:
        return hit
    if "hookspath" in c:
        return "core.hooksPath の指定・変更はフックの迂回です"
    if C.HOOK_NAME_PREFIX in c:
        return "auto-flow-guard 設定・プローブ ref の操作は禁止です"
    if (".git/hooks" in c or "auto-flow-orig" in c or ".git/config" in c) \
            and any(w in c for w in WRITE_WORDS):
        return "Git フック・.git/config の改変は禁止です"
    if ("auto-flow-auth" in c or "auto-flow/tokens" in c) and any(w in c for w in WRITE_WORDS):
        return "起動認可レコード・トークンの改変は禁止です"
    if ("update-ref" in c and "refs/remotes" in c) or ":refs/remotes" in c:
        return "リモート追跡 ref の直接更新は禁止です"
    if re.search(r"git_config_(key_\d+|parameters)=\S*(url\.\S*insteadof|remote\.\S*\.(url|pushurl)"
                 r"|branch\.\S*\.remote)", c):
        return "remote URL / upstream / insteadOf の設定・注入は禁止です"
    if "install_guards.py" in c and "uninstall" in c:
        return "実行中のガード撤去は禁止です"
    return None


def deny(reason):
    sys.stderr.write("%s %s。%s\n" % (C.GUARD_TAG, reason, C.ABORT_HINT))
    return 2


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    ti = data.get("tool_input") or {}
    command = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(command, str):
        return 0
    cwd = data.get("cwd") or os.getcwd()
    extra = [cwd]
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        rc, rp = os.path.realpath(cwd), os.path.realpath(proj)
        if rc == rp or rc.startswith(rp + os.sep):
            extra.append(proj)
    c = command.lower()
    try:
        run = C.find_active_run(cwd, extra)
    except RuntimeError as e:
        if re.search(r"\bgh\s+pr\s+merge\b", c) or rule_hit(c):
            return deny("状態ファイルを読めないため拒否します（%s）" % e)
        return 0
    if run is None:
        return 0
    try:
        if re.search(r"\bgh\s+pr\s+merge\b", c):
            reason, _ = C.validate_gate(run)
            if reason:
                return deny("gh pr merge は gate.json 合格後のみ許可されます（現状: %s）" % reason)
        hit = rule_hit(c)
        if hit:
            return deny(hit)
    except Exception as e:
        return deny("内部エラーのため拒否します（%s: %s）" % (type(e).__name__, e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
