#!/usr/bin/env python3
"""auto-flow 共通モジュール（git_guard.py / install_guards.py / af_guard.py が共有）。

標準ライブラリのみ・Python 3.9 互換。
"""
import glob
import json
import os
import re
import subprocess
import unicodedata
from datetime import datetime

PROTECTED_DEFAULT = ("main", "master")
ZERO = "0" * 40
PROBE_REF = "refs/auto-flow-guard/probe"
HOOK_NAME_PREFIX = "auto-flow-guard"  # 設定ベースフックは hook.auto-flow-guard-<event>.*
SHIM_MARKER = "# auto-flow-guard shim v1"
EVENTS = ("reference-transaction", "pre-push", "pre-commit")
GATE_CHECKS = ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8")
GATE_SCHEMA_VERSION = 3
TOKEN_TTL = 600  # 起動トークンの有効秒数
AUTH_SKEW = 60  # 時計ずれ許容秒数
AUTH_DIR_NAME = "auto-flow-auth"
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
AUTH_ID_RE = re.compile(r"^[0-9a-f]{32}$")
TRIGGERS = ("オートフロー", "auto-flow", "自律実行して", "自動で最後まで進めて", "全自動で進めて")
GUARD_TAG = "[auto-flow guard]"
ABORT_HINT = "不要な実行なら .auto-flow/<ID>/state.json の status を aborted にしてください。"

# ~/.claude/skills/safe-push/scripts/check_secrets.py の EXCLUDED_FILE_PATTERNS のコピー + 追加分。
# check_secrets.py と同期すること。
SENSITIVE_PATTERNS = [
    r"\.env(\.(local|production|development|staging))?$",
    r"node_modules/",
    r"\.log$",
    r"\.DS_Store$",
    r"\.(pem|key|p12|pfx)$",
    r"credentials\.json$",
    r"service[-_]account\.json$",
    # --- 以下 auto-flow 追加分 ---
    r"(^|/)\.auto-flow(/|$)",
    r"(^|/)\.env\.(?!example$|sample$|template$).+$",
    r"(^|/)id_(rsa|ed25519)$",
    r"\.keystore$",
    r"\.jks$",
]

_STRIP_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_PREFIX", "GIT_COMMON_DIR")


def tokens_dir():
    return os.path.join(os.path.expanduser("~"), ".claude", "auto-flow", "tokens")


def match_trigger(text):
    """起動語（NFKC・小文字化後の部分一致）。最初に一致した起動語、無ければ None。"""
    if not isinstance(text, str):
        return None
    t = unicodedata.normalize("NFKC", text).lower()
    for w in TRIGGERS:
        if w.lower() in t:
            return w
    return None


def common_dir(root):
    rc, out = git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return out.strip() if rc == 0 and out.strip() else None


def parse_iso(s):
    """ISO 8601 文字列 -> epoch 秒。tz 無しはローカル時刻。失敗時 None。
    Python 3.9 の fromisoformat 向けに Z・+0900・小数秒桁数を正規化する。"""
    if not isinstance(s, str):
        return None
    try:
        s = s.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
        m = re.match(r"^(.*?T\d{2}:\d{2}:\d{2})\.(\d+)(.*)$", s)
        if m:
            s = "%s.%s%s" % (m.group(1), (m.group(2) + "000000")[:6], m.group(3))
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_auth(root, state, run_id=None):
    """起動認可の検証。合格なら None、不合格なら理由。"""
    aid = state.get("auth_id")
    if not isinstance(aid, str) or not AUTH_ID_RE.match(aid):
        return "起動認可なし（state.auth_id 未記録）"
    cd = common_dir(root)
    if not cd:
        return "Git 共通ディレクトリを取得できない"
    try:
        with open(os.path.join(cd, AUTH_DIR_NAME, aid + ".json"), encoding="utf-8") as f:
            rec = json.load(f)
    except Exception:
        return "起動認可レコードなし"
    if not isinstance(rec, dict):
        return "起動認可レコードの形式が不正"
    run_id = state.get("run_id") or run_id
    if rec.get("auth_id") != aid or not run_id or rec.get("run_id") != run_id:
        return "起動認可レコードが別の実行のもの"
    if not rec.get("session_id"):
        return "起動認可レコードに session_id がない"
    tc, ca = rec.get("token_created_at"), rec.get("consumed_at")
    if not (_num(tc) and _num(ca)) or not (0 <= ca - tc <= TOKEN_TTL):
        return "トークン期限切れで発行された認可"
    t0 = parse_iso(state.get("resumed_at") or state.get("started_at"))
    if t0 is None or not (t0 - TOKEN_TTL <= ca <= t0 + AUTH_SKEW):
        return "認可時刻と開始(再開)時刻が整合しない"
    return None


def is_sensitive(path):
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return any(re.search(pat, p) for pat in SENSITIVE_PATTERNS)


def git(cwd, *args, **kw):
    """git -C cwd args... を実行して (rc, stdout) を返す。例外時は (1, "")。"""
    timeout = kw.get("timeout", 5)
    env = dict(os.environ)
    if not kw.get("keep_env"):
        for k in _STRIP_ENV:
            env.pop(k, None)
    if kw.get("scrub_config"):
        for k in list(env):
            if k == "GIT_CONFIG_PARAMETERS" or k == "GIT_CONFIG_COUNT" \
                    or k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_"):
                env.pop(k)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.update(kw.get("env") or {})
    try:
        r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True,
                           timeout=timeout, check=False, env=env, input=kw.get("input"))
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def candidate_roots(start, extra=()):
    roots = []

    def add(p):
        if p and p not in roots:
            roots.append(p)

    if start and os.path.isdir(start):
        rc, out = git(start, "rev-parse", "--show-toplevel")
        if rc == 0:
            add(out.strip())
        rc, out = git(start, "worktree", "list", "--porcelain")
        if rc == 0:
            for line in out.splitlines():
                if line.startswith("worktree "):
                    add(line[len("worktree "):].strip())
    for e in extra:
        add(e)
    return roots


def hook_extra_roots():
    """フック内用。git が渡す GIT_DIR / GIT_WORK_TREE を保持して common dir を求め、
    その全 worktree を候補にする（repo 外から GIT_DIR / --git-dir で操作されても検出するため）。"""
    roots = []
    wt = os.environ.get("GIT_WORK_TREE")
    if wt and os.path.isdir(wt):
        roots.append(os.path.realpath(wt))
    rc, out = git(os.getcwd(), "rev-parse", "--path-format=absolute", "--git-common-dir",
                  keep_env=True)
    common = out.strip() if rc == 0 else ""
    if common:
        rc, out = git(os.getcwd(), "--git-dir=%s" % common, "worktree", "list", "--porcelain")
        if rc == 0:
            for line in out.splitlines():
                if line.startswith("worktree "):
                    roots.append(line[len("worktree "):].strip())
    return roots


def find_active_run(start, extra=()):
    """status=running の最新 run を返す。無ければ None。
    state.json が壊れていて生テキストが running を示すときだけ RuntimeError。"""
    found = []
    for root in candidate_roots(start, extra):
        for path in glob.glob(os.path.join(root, ".auto-flow", "*", "state.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
            except Exception:
                continue
            try:
                state = json.loads(raw)
            except Exception:
                if re.search(r'"status"\s*:\s*"running"', raw):
                    raise RuntimeError("state.json が破損しています: %s" % path)
                continue
            if isinstance(state, dict) and state.get("status") == "running":
                d = os.path.dirname(path)
                found.append({"root": root, "dir": d, "state": state,
                              "run_id": os.path.basename(d)})
    if not found:
        return None
    return max(found, key=lambda x: x["run_id"])


def protected_branches(run):
    s = set(PROTECTED_DEFAULT)
    base = run["state"].get("base_branch")
    if isinstance(base, str) and base:
        s.add(base)
    return s


def validate_gate(run):
    """(reason, gate)。合格なら (None, gate)。"""
    path = os.path.join(run["dir"], "gate.json")
    if not os.path.isfile(path):
        return "gate.json なし", None
    try:
        with open(path, encoding="utf-8") as f:
            gate = json.load(f)
    except Exception:
        return "gate.json を読めない", None
    if not isinstance(gate, dict):
        return "gate.json の形式が不正", None
    if gate.get("schema_version") != GATE_SCHEMA_VERSION:
        return "schema_version が %d ではない" % GATE_SCHEMA_VERSION, None
    state = run["state"]
    if gate.get("run_id") != (state.get("run_id") or run["run_id"]):
        return "gate.json の run_id が state.json と不一致", None
    if gate.get("passed") is not True:
        return "passed が true ではない", None
    checks = gate.get("checks")
    if not isinstance(checks, dict):
        return "checks がない", None
    for k in GATE_CHECKS:
        c = checks.get(k)
        if not isinstance(c, dict) or c.get("pass") is not True:
            return "%s が合格ではない" % k, None
    if gate.get("decision") != "merge":
        return "decision が merge ではない", None
    auth = validate_auth(run["root"], state, run["run_id"])
    if auth:
        return "起動認可なし: %s" % auth, None
    wb = state.get("work_branch")
    head = None
    if wb:
        rc, out = git(run["root"], "rev-parse", "--verify", "refs/heads/%s" % wb)
        head = out.strip() if rc == 0 else None
    if not head:
        return "作業ブランチの HEAD を取得できない", None
    if gate.get("head_sha") != head:
        return "head_sha が作業ブランチの現在値と不一致（ゲート判定後にコミットが追加された）", None
    return None, gate


def is_ancestor(root, a, b):
    rc, _ = git(root, "merge-base", "--is-ancestor", a, b)
    return rc == 0


def parents(root, sha):
    rc, out = git(root, "rev-list", "--parents", "-n1", sha)
    return out.split()[1:] if rc == 0 else []
