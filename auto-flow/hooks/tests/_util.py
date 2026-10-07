"""テスト共通ヘルパー。実 git を使い、ユーザー設定から隔離する。Python 3.9 標準ライブラリのみ。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(HOOKS, "install_guards.py")
AF_GUARD = os.path.join(HOOKS, "af_guard.py")
RUN_ID = "20260101-000000-test"
WORK = "auto-flow/test"
CHECKS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"]


def make_env(tmp):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "CLAUDE_PROJECT_DIR"}
    empty = os.path.join(tmp, "empty.gitconfig")
    open(empty, "a").close()
    home = os.path.join(tmp, "home")
    os.makedirs(home, exist_ok=True)
    env.update({
        "HOME": home,
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": empty,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_TERMINAL_PROMPT": "0",
    })
    return env


class Fixture:
    def __init__(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="af guard "))
        self.env = make_env(self.tmp)
        self.repo = os.path.join(self.tmp, "repo")
        self.remote = os.path.join(self.tmp, "remote.git")
        self.other = os.path.join(self.tmp, "other")
        self.sh("git init -q --bare -b main '%s'" % self.remote, cwd=self.tmp)
        self.sh("git init -q -b main repo", cwd=self.tmp)
        self.sh("echo 1 > a.txt && git add a.txt && git commit -qm c1 && "
                "echo 2 >> a.txt && git commit -qam c2 && "
                "git remote add origin '%s' && git push -q -u origin main" % self.remote)
        self.sh("git switch -q -c %s && echo w > work.txt && git add work.txt && "
                "git commit -qm work && git switch -q main" % WORK)
        self.sh("git clone -q '%s' other" % self.remote, cwd=self.tmp)
        with open(os.path.join(self.repo, ".git", "info", "exclude"), "a") as f:
            f.write(".auto-flow/\n")
        self.m0 = self.rev("main")
        self.w0 = self.rev(WORK)
        self.sh("git switch -q %s" % WORK)
        self.run_dir = os.path.join(self.repo, ".auto-flow", RUN_ID)
        os.makedirs(self.run_dir)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sh(self, cmd, cwd=None):
        r = subprocess.run(["bash", "-c", cmd], cwd=cwd or self.repo, env=self.env,
                           capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout, r.stderr

    def rev(self, ref, cwd=None):
        rc, out, _ = self.sh("git rev-parse -q --verify %s" % ref, cwd=cwd)
        return out.strip() if rc == 0 else None

    def remote_rev(self, ref="refs/heads/main"):
        return self.rev(ref, cwd=self.remote)

    AUTH_ID = "a" * 32

    def write_auth_record(self, auth_id=None, **over):
        auth_id = auth_id or self.AUTH_ID
        d = os.path.join(self.repo, ".git", "auto-flow-auth")
        os.makedirs(d, exist_ok=True)
        now = time.time()
        rec = {"schema_version": 1, "auth_id": auth_id, "run_id": RUN_ID, "session_id": "s",
               "token_created_at": now - 5, "consumed_at": now, "trigger": "auto-flow",
               "prompt_head": "x", "repo_top": self.repo}
        rec.update(over)
        with open(os.path.join(d, auth_id + ".json"), "w") as f:
            json.dump(rec, f)

    def write_state(self, status="running", raw=None, auth=True, started_at=None, **over):
        path = os.path.join(self.run_dir, "state.json")
        if raw is not None:
            with open(path, "w") as f:
                f.write(raw)
            return
        st = {"schema_version": 2, "run_id": RUN_ID, "status": status,
              "base_branch": "main", "work_branch": WORK,
              "started_at": started_at or datetime.now(timezone.utc).isoformat()}
        if auth:
            self.write_auth_record()
            st["auth_id"] = self.AUTH_ID
        st.update(over)
        with open(path, "w") as f:
            json.dump(st, f)

    def tokens_path(self, session):
        return os.path.join(self.env["HOME"], ".claude", "auto-flow", "tokens", session + ".json")

    def put_token(self, session, age=0, **over):
        p = self.tokens_path(session)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tok = {"schema_version": 1, "session_id": session, "created_at": time.time() - age,
               "trigger": "auto-flow", "prompt_head": "auto-flow test"}
        tok.update(over)
        with open(p, "w") as f:
            json.dump(tok, f)
        return p

    def install_auth(self, session, run_id, mode="config", repo=None, extra=()):
        args = [sys.executable, INSTALL, "install", "--repo", repo or self.repo, "--mode", mode]
        if session is not None:
            args += ["--session", session]
        if run_id is not None:
            args += ["--run-id", run_id]
        r = subprocess.run(args + list(extra), env=self.env, capture_output=True, text=True,
                           timeout=120)
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])

    def write_gate(self, drop=(), checks=None, **over):
        g = {"schema_version": 3, "run_id": RUN_ID, "passed": True, "decision": "merge",
             "head_sha": self.rev(WORK),
             "checks": {k: {"pass": True, "evidence": "x"} for k in CHECKS if k not in drop}}
        for k, v in (checks or {}).items():
            g["checks"][k] = v
        g.update(over)
        with open(os.path.join(self.run_dir, "gate.json"), "w") as f:
            json.dump(g, f)

    def clear_gate(self):
        p = os.path.join(self.run_dir, "gate.json")
        if os.path.exists(p):
            os.remove(p)

    def install(self, mode, script=INSTALL):
        r = subprocess.run([sys.executable, script, "install", "--repo", self.repo, "--mode", mode],
                           env=self.env, capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def installer(self, action, mode="auto", script=INSTALL):
        r = subprocess.run([sys.executable, script, action, "--repo", self.repo, "--mode", mode],
                           env=self.env, capture_output=True, text=True, timeout=120)
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])

    def reset_main(self, running=True):
        """ガードを止めた状態で main・work・remote・作業ツリーを初期状態に戻す。"""
        self.write_state("completed")
        self.clear_gate()
        script = """
export GIT_CONFIG_COUNT=4 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null
export GIT_CONFIG_KEY_1=hook.auto-flow-guard-reference-transaction.enabled GIT_CONFIG_VALUE_1=false
export GIT_CONFIG_KEY_2=hook.auto-flow-guard-pre-push.enabled GIT_CONFIG_VALUE_2=false
export GIT_CONFIG_KEY_3=hook.auto-flow-guard-pre-commit.enabled GIT_CONFIG_VALUE_3=false
git rebase --abort 2>/dev/null; git merge --abort 2>/dev/null
git cherry-pick --quit 2>/dev/null; git revert --quit 2>/dev/null
git symbolic-ref HEAD refs/heads/{w}
git update-ref --no-deref -d refs/heads/main
git update-ref refs/heads/main {m0}
git update-ref refs/heads/{w} {w0}
git reset -q --hard {w0}
git clean -fdq
for wt in $(git worktree list --porcelain | sed -n 's/^worktree //p' | tail -n +2); do
  git worktree remove --force "$wt"; done
git worktree prune
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  case "$b" in main|{w}) ;; *) git update-ref -d refs/heads/$b ;; esac; done
git update-ref refs/remotes/origin/main {m0}
git branch -q --set-upstream-to=origin/main main
git --git-dir='{remote}' update-ref refs/heads/main {m0}
git -C '{other}' fetch -q 2>/dev/null; git -C '{other}' reset -q --hard {m0}
""".format(w=WORK, m0=self.m0, w0=self.w0, remote=self.remote, other=self.other)
        rc, out, err = self.sh(script)
        assert self.rev("main") == self.m0 and self.rev(WORK) == self.w0, err
        self.write_state("running" if running else "completed")


class ConfigModeMixin:
    MODE = "config"


class ShimModeMixin:
    MODE = "shim"
