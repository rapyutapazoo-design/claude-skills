#!/usr/bin/env python3
"""auto-flow 起動トークン発行フック（UserPromptSubmit / UserPromptExpansion）。

起動語を含むユーザー入力のときだけ ~/.claude/auto-flow/tokens/<session_id>.json を発行する。
どの経路でも stdout/stderr に何も出さず exit 0（stdout はプロンプト文脈に混入するため）。
標準ライブラリのみ・Python 3.9 互換。
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime

AUTO_TURN_PREFIXES = ("<task-notification", "<system-reminder", "<scheduled-task")
CLEAN_AGE = 3600
CLEAN_MAX = 200


def _clean(d):
    now = time.time()
    n = 0
    try:
        names = os.listdir(d)
    except Exception:
        return
    for name in names:
        if not (name.endswith(".json") or ".consumed-" in name):
            continue
        n += 1
        if n > CLEAN_MAX:
            break
        p = os.path.join(d, name)
        try:
            if now - os.path.getmtime(p) > CLEAN_AGE:
                os.remove(p)
        except Exception:
            pass


def run():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import af_common as C
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        return
    ev = data.get("hook_event_name")
    if ev not in ("UserPromptSubmit", "UserPromptExpansion") or "agent_id" in data:
        return
    sid = data.get("session_id")
    if not isinstance(sid, str) or not C.SESSION_RE.match(sid):
        return
    prompt = data.get("prompt")
    if not isinstance(prompt, str) or prompt.lstrip().startswith(AUTO_TURN_PREFIXES):
        return
    trig = C.match_trigger(prompt)
    if trig is None:
        return
    d = C.tokens_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    _clean(d)
    now = time.time()
    tok = {"schema_version": 1, "session_id": sid, "created_at": now,
           "created_iso": datetime.now().astimezone().isoformat(),
           "event": ev, "trigger": trig, "prompt_head": prompt[:200],
           "cwd": data.get("cwd") if isinstance(data.get("cwd"), str) else None}
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tok, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, os.path.join(d, sid + ".json"))
    except BaseException:
        try:
            os.remove(tmp)
        except Exception:
            pass
        raise


def main():
    try:
        run()
    except BaseException:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
