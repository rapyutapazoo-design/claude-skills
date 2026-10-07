#!/usr/bin/env python3
"""auto-flow Git ガードの設置・確認・撤去。

使い方: install_guards.py {install|check|uninstall} [--repo PATH] [--mode auto|config|shim]
                          [--session SESSION_ID] [--run-id RUN_ID]
結果は JSON 1行を stdout に出す。ok なら exit 0、それ以外は exit 1。
  起動認可: install に --session と --run-id を渡すと ~/.claude/auto-flow/tokens/<session>.json
    （prompt_token.py が発行）を消費し、<git共通dir>/auto-flow-auth/<auth_id>.json を作る。
    結果の authorized / auth_id / auth_reason に出る（ok・終了コードには影響しない）。
    check --run-id は state.json の auth_id を検証して authorized に反映する。
  config モード: git の設定ベースフック hook.auto-flow-guard-<event>.{command,event}
  shim モード  : hooks ディレクトリにシムを置く（既存フックは <event>.auto-flow-orig に退避して連鎖）
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import af_common as C  # noqa: E402

GATE_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "af_gate.sh")


def git(cwd, *args, **kw):
    kw.setdefault("timeout", 30)
    return C.git(cwd, *args, **kw)


def name_of(event):
    return "%s-%s" % (C.HOOK_NAME_PREFIX, event)


def config_command(event):
    """設定ベースフックのコマンド。ガード一式が無ければ素通り(exit 0)。"""
    py, gate = shlex.quote(sys.executable), shlex.quote(GATE_SH)
    skip = '[ "$1" = prepared ] || exit 0; ' if event == "reference-transaction" else ""
    return 'f(){ %s[ -f %s ] || exit 0; exec /bin/sh %s %s %s "$@"; }; f' % (skip, gate, gate, py, event)


def shim_text(event):
    py, gate = shlex.quote(sys.executable), shlex.quote(GATE_SH)
    stdin_part = ': > "$tmp"' if event == "pre-commit" else 'cat > "$tmp"'
    early = ('[ "$1" = prepared ] || [ -x "$0.auto-flow-orig" ] || exit 0\n'
             if event == "reference-transaction" else "")
    return """#!/bin/sh
%s
%sorig="$0.auto-flow-orig"
tmp="$(mktemp "${TMPDIR:-/tmp}/afguard.XXXXXX")" || exit 1
trap 'rm -f "$tmp"' EXIT
%s
if [ -x "$orig" ]; then
  "$orig" "$@" < "$tmp" || exit $?
fi
[ -f %s ] || exit 0
/bin/sh %s %s %s "$@" < "$tmp"
exit $?
""" % (C.SHIM_MARKER, early, stdin_part, gate, gate, py, event)


def has_marker(path):
    try:
        with open(path, encoding="utf-8") as f:
            return C.SHIM_MARKER in f.read()
    except Exception:
        return False


def config_supported():
    """使い捨てリポジトリで設定ベースフックが reference-transaction で発火するか確認する。"""
    try:
        with tempfile.TemporaryDirectory(prefix="af probe ") as d:
            marker = os.path.join(d, "marker")
            repo = os.path.join(d, "r")
            os.mkdir(repo)
            iso = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
            if git(repo, "init", "-q", env=iso)[0] != 0:
                return False
            cmd = "%s -c %s" % (shlex.quote(sys.executable), shlex.quote(
                "import sys;open(%r,'a').write(' '.join(sys.argv[1:])+chr(10))" % marker))
            git(repo, "config", "hook.af-probe.command", cmd)
            git(repo, "config", "hook.af-probe.event", "reference-transaction")
            git(repo, "-c", "user.name=p", "-c", "user.email=p@p", "-c", "commit.gpgsign=false",
                "commit", "--allow-empty", "-q", "-m", "p",
                env={"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
            with open(marker, encoding="utf-8") as f:
                return "prepared" in f.read()
    except Exception:
        return False


class Ctx:
    def __init__(self, repo):
        rc, out = git(repo, "rev-parse", "--show-toplevel")
        self.top = out.strip() if rc == 0 else None
        self.hooks_dir = None
        if self.top:
            rc, out = git(self.top, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
            if rc == 0:
                self.hooks_dir = out.strip()


def result(action, mode=None, ok=False, reason=None, ctx=None, events=None, chained=None,
           probe="skipped"):
    rc, out = git(".", "--version")
    return {"ok": ok, "action": action, "mode": mode,
            "hooks_dir": ctx.hooks_dir if ctx else None,
            "events": events or {}, "chained": chained or [], "probe": probe,
            "git_version": out.strip(), "reason": reason,
            "authorized": False, "auth_id": None, "auth_reason": None}


def detect_mode(ctx):
    rc, out = git(ctx.top, "config", "--local", "--get-regexp", r"^hook\.%s-" % C.HOOK_NAME_PREFIX)
    if rc == 0 and out.strip():
        return "config"
    if ctx.hooks_dir:
        for ev in C.EVENTS:
            if has_marker(os.path.join(ctx.hooks_dir, ev)):
                return "shim"
    return None


def probe(ctx):
    rc, out = git(ctx.top, "rev-parse", "-q", "--verify", "HEAD")
    sha = out.strip() if rc == 0 else None
    if not sha:
        rc, out = git(ctx.top, "hash-object", "-t", "tree", "-w", "--stdin", input="")
        sha = out.strip() if rc == 0 else None
    if not sha:
        return "skipped"
    env = dict(os.environ)
    for k in ("GIT_DIR", "GIT_WORK_TREE"):
        env.pop(k, None)
    try:
        r = subprocess.run(["git", "-C", ctx.top, "update-ref", C.PROBE_REF, sha],
                           capture_output=True, text=True, timeout=30, check=False, env=env)
    except Exception:
        return "skipped"
    if r.returncode != 0 and C.GUARD_TAG in r.stderr:
        return "denied"
    if r.returncode == 0:
        git(ctx.top, "update-ref", "-d", C.PROBE_REF)
    return "not_denied"


def do_check(ctx, action="check"):
    mode = detect_mode(ctx)
    events = {}
    for ev in C.EVENTS:
        st = "missing"
        if mode == "config":
            rc, out = git(ctx.top, "hook", "list", ev)
            if rc == 0 and name_of(ev) in out:
                st = "ok"
        elif mode == "shim":
            p = os.path.join(ctx.hooks_dir, ev)
            if has_marker(p) and os.access(p, os.X_OK):
                st = "ok"
        events[ev] = st
    pr = probe(ctx)
    ok = mode is not None and all(v == "ok" for v in events.values()) and pr == "denied"
    reason = None
    if not ok:
        reason = ("ガード未設置" if mode is None else
                  "設置不備: %s / probe=%s" % (
                      ",".join(e for e, v in events.items() if v != "ok") or "-", pr))
    return result(action, mode, ok, reason, ctx, events, probe=pr)


def install_config(ctx):
    events = {}
    for ev in C.EVENTS:
        n = "hook.%s" % name_of(ev)
        for key, val in (("command", config_command(ev)), ("event", ev)):
            rc, _ = git(ctx.top, "config", "--local", "--replace-all", "%s.%s" % (n, key), val)
            if rc != 0:
                return None, "git config の書き込みに失敗: %s.%s" % (n, key)
        git(ctx.top, "config", "--local", "--unset-all", n + ".enabled")
        events[ev] = "installed"
    return events, None


def install_shim(ctx):
    rc, out = git(ctx.top, "config", "--show-scope", "--get", "core.hooksPath")
    if rc == 0 and out.strip():
        scope = out.split()[0]
        if scope != "local":
            return None, None, "全リポジトリ共通の hooks ディレクトリには設置しない（core.hooksPath: %s スコープ）" % scope
        hd = os.path.realpath(ctx.hooks_dir)
        top = os.path.realpath(ctx.top)
        if hd.startswith(top + os.sep):
            rc, out = git(ctx.top, "ls-files", "--", hd)
            if rc == 0 and out.strip():
                return None, None, "core.hooksPath が Git 管理下のため設置しない"
    hd = ctx.hooks_dir
    os.makedirs(hd, exist_ok=True)
    events, chained = {}, []
    # 事前検査（途中で中止して半端な状態にしない）
    for ev in C.EVENTS:
        p = os.path.join(hd, ev)
        orig = p + ".auto-flow-orig"
        if os.path.exists(p) and not has_marker(p) and os.path.exists(orig):
            with open(p, "rb") as a, open(orig, "rb") as b:
                if a.read() != b.read():
                    return None, None, "%s.auto-flow-orig が既に存在し内容が異なるため中止" % ev
    for ev in C.EVENTS:
        p = os.path.join(hd, ev)
        orig = p + ".auto-flow-orig"
        st = "installed"
        if os.path.lexists(p):
            if has_marker(p):
                st = "ok"
            else:
                if os.path.exists(orig):
                    os.remove(p)
                else:
                    os.replace(p, orig)
                st = "chained"
                chained.append(ev)
        with open(p, "w", encoding="utf-8") as f:
            f.write(shim_text(ev))
        os.chmod(p, 0o755)
        events[ev] = st
    return events, chained, None


RUN_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,30}$")
RECORD_MAX_AGE = 7 * 86400


def _atomic_write(d, name, obj):
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, os.path.join(d, name))
    except BaseException:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def _revoke_run_records(d, run_id, now=None):
    """d 内の run_id 一致レコードと期限切れ（7日超）レコードを削除する。"""
    now = now or time.time()
    try:
        names = os.listdir(d)
    except Exception:
        return
    for name in names:
        p = os.path.join(d, name)
        try:
            if not name.endswith(".json"):
                continue
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
            if (isinstance(rec, dict) and rec.get("run_id") == run_id) \
                    or now - os.path.getmtime(p) > RECORD_MAX_AGE:
                os.remove(p)
        except Exception:
            pass


def authorize(ctx, session, run_id):
    """起動トークンを消費して認可レコードを作る。(auth_id, reason)。"""
    if not session:
        return None, "session 未指定"
    if not isinstance(session, str) or not C.SESSION_RE.match(session):
        return None, "session_id が不正"
    if not run_id or not RUN_ID_RE.match(run_id):
        return None, "run_id 未指定/不正"
    # 引数検証通過後・トークン確保前に同 run_id の旧認可を無条件で失効させる（失敗時も旧認可は残さない）
    cd = C.common_dir(ctx.top)
    if cd:
        _revoke_run_records(os.path.join(cd, C.AUTH_DIR_NAME), run_id)
    td = C.tokens_dir()
    tok = os.path.join(td, session + ".json")
    claimed = "%s.consumed-%d" % (tok, os.getpid())
    try:
        os.rename(tok, claimed)
    except Exception:
        n = 0
        try:
            for name in os.listdir(td):
                p = os.path.join(td, name)
                if name.endswith(".json") and time.time() - os.path.getmtime(p) <= C.TOKEN_TTL:
                    n += 1
        except Exception:
            pass
        return None, ("起動トークンなし（起動語を含むユーザー発話が無い／フック未設定／session_id 不一致）"
                      " 他セッションの有効トークン: %d" % n)
    try:
        try:
            with open(claimed, encoding="utf-8") as f:
                t = json.load(f)
        except Exception:
            return None, "起動トークンを読めない"
    finally:
        try:
            os.remove(claimed)
        except Exception:
            pass
    now = time.time()
    if not isinstance(t, dict) or t.get("session_id") != session:
        return None, "起動トークンの session_id が不一致"
    ca = t.get("created_at")
    if not C._num(ca):
        return None, "起動トークンの created_at が不正"
    if now - ca > C.TOKEN_TTL:
        return None, "トークン期限切れ"
    if ca > now + C.AUTH_SKEW:
        return None, "トークンの時刻が未来"
    if not cd:
        return None, "Git 共通ディレクトリを取得できない"
    d = os.path.join(cd, C.AUTH_DIR_NAME)
    os.makedirs(d, mode=0o700, exist_ok=True)
    _revoke_run_records(d, run_id, now)
    aid = uuid.uuid4().hex
    head = t.get("prompt_head")
    _atomic_write(d, aid + ".json", {
        "schema_version": 1, "auth_id": aid, "run_id": run_id, "session_id": session,
        "token_created_at": ca, "consumed_at": now, "trigger": t.get("trigger"),
        "prompt_head": head if isinstance(head, str) else "", "repo_top": ctx.top})
    return aid, None


def do_install(ctx, mode, session=None, run_id=None):
    if mode == "auto":
        mode = "config" if config_supported() else "shim"
    if mode == "config":
        events, err = install_config(ctx)
        chained = []
    else:
        events, chained, err = install_shim(ctx)
    if err:
        r = result("install", mode, False, err, ctx)
    else:
        r = do_check(ctx, "install")
        r["chained"] = chained
        for ev, st in events.items():
            if r["events"].get(ev) == "ok":
                r["events"][ev] = st
    try:
        aid, reason = authorize(ctx, session, run_id)
    except Exception as e:
        aid, reason = None, "内部エラー: %s: %s" % (type(e).__name__, e)
    r["authorized"], r["auth_id"], r["auth_reason"] = aid is not None, aid, reason
    return r


def check_auth(ctx, r, run_id):
    """check --run-id: state.json の起動認可を検証して r に反映する（ok には混ぜない）。"""
    if not run_id or not RUN_ID_RE.match(run_id):
        r["auth_reason"] = "run_id 未指定/不正" if run_id else "run_id 未指定"
        return r
    try:
        with open(os.path.join(ctx.top, ".auto-flow", run_id, "state.json"), encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            raise ValueError("state.json の形式が不正")
        reason = C.validate_auth(ctx.top, state, run_id)
    except Exception as e:
        reason = "state.json を読めない: %s" % type(e).__name__
    r["authorized"] = reason is None
    r["auth_id"] = state.get("auth_id") if reason is None else None
    r["auth_reason"] = reason
    return r


def do_uninstall(ctx, mode):
    try:
        run = C.find_active_run(ctx.top)
    except RuntimeError:
        run = True
    if run:
        return result("uninstall", None, False, "実行中(state.json running)は撤去できません", ctx)
    events = {}
    if mode in ("auto", "config"):
        for ev in C.EVENTS:
            git(ctx.top, "config", "--local", "--remove-section", "hook.%s" % name_of(ev))
            events[ev] = "removed"
    if mode in ("auto", "shim") and ctx.hooks_dir and os.path.isdir(ctx.hooks_dir):
        for ev in C.EVENTS:
            p = os.path.join(ctx.hooks_dir, ev)
            orig = p + ".auto-flow-orig"
            if has_marker(p):
                os.remove(p)
                events[ev] = "removed"
            if os.path.exists(orig) and not os.path.exists(p):
                os.replace(orig, p)
                events[ev] = "restored"
    return result("uninstall", None, True, None, ctx, events)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("install", "check", "uninstall"))
    ap.add_argument("--repo", default=".")
    ap.add_argument("--mode", choices=("auto", "config", "shim"), default="auto")
    ap.add_argument("--session", default=None)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args(argv)
    try:
        ctx = Ctx(a.repo)
        if not ctx.top:
            r = result(a.action, None, False, "Git リポジトリではありません")
        elif a.action == "install":
            r = do_install(ctx, a.mode, a.session, a.run_id)
        elif a.action == "check":
            r = do_check(ctx)
            if a.run_id:
                r = check_auth(ctx, r, a.run_id)
        else:
            r = do_uninstall(ctx, a.mode)
    except Exception as e:
        r = result(a.action, None, False, "内部エラー: %s: %s" % (type(e).__name__, e))
    sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
