"""層2（af_guard.py）。コマンド文字列を stdin JSON で渡し、終了コードを確認する。"""
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import AF_GUARD, INSTALL, Fixture  # noqa: E402

DENY = [
    "gh pr merge 1 --merge",
    "git push --no-verify origin x",
    "git commit -n -m x",
    "git commit -nm x",
    "git -c core.hooksPath=/dev/null update-ref refs/heads/main HEAD",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git merge x",
    "git config --unset hook.auto-flow-guard-pre-push.event",
    "git -c hook.auto-flow-guard-reference-transaction.enabled=false merge x",
    "rm .git/hooks/reference-transaction",
    "mv .git/hooks/pre-commit.auto-flow-orig x",
    "git update-ref refs/remotes/origin/main HEAD",
    "python3 %s uninstall" % INSTALL,
    "git send-pack ../remote.git main",
    "git fetch . x:refs/remotes/origin/main",
    "git remote add evil .",
    "git remote set-url origin .",
    "git commit -m x -n",
    "cd x && git commit -am msg -n",
    "bash -c 'git commit -n -m x'",
    "git -c url.file:///x.insteadOf=file:///y merge --ff-only side",
    "git -c remote.origin.url=/evil fetch origin",
    "git -c branch.main.remote=evil pull --ff-only",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=url.x.insteadOf GIT_CONFIG_VALUE_0=y git merge --ff-only side",
    "git config url.file:///x.insteadOf file:///y",
    "git config remote.origin.url /evil",
    "git config --unset remote.origin.url",
]
ALLOW_RUNNING = [
    "cat .git/hooks/pre-push",
    'git commit -m "x"',
    'git commit -m "use -n here"',
    'git commit -am "fix -n handling" --allow-empty',
    'git commit -m "docs: remote add and send-pack notes"',
    "git remote -v",
    "git config remote.origin.url",
    "git config --get remote.origin.url",
    "git config --get-regexp 'remote\\..*\\.url'",
    "git fetch origin",
    "git push origin auto-flow/test",
    "ls -la",
    "python3 %s check" % INSTALL,
]
ALLOW_IDLE = ["gh pr merge 1", "git push --no-verify", "git -c core.hooksPath=/dev/null status",
              "rm .git/hooks/pre-push"]


class TestAfGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def call(self, command, tool="Bash"):
        payload = {"tool_name": tool, "tool_input": {"command": command}, "cwd": self.fx.repo}
        r = subprocess.run([sys.executable, AF_GUARD], input=json.dumps(payload), env=self.fx.env,
                           capture_output=True, text=True, timeout=30)
        return r.returncode, r.stderr

    def test_idle_all_allowed(self):
        for status in ("none", "completed"):
            os_state = os.path.join(self.fx.run_dir, "state.json")
            if status == "none":
                if os.path.exists(os_state):
                    os.remove(os_state)
            else:
                self.fx.write_state("completed")
            for c in ALLOW_IDLE:
                with self.subTest(status=status, c=c):
                    self.assertEqual(self.call(c)[0], 0)

    def test_running_denied(self):
        self.fx.write_state("running"); self.fx.clear_gate()
        for c in DENY:
            with self.subTest(c=c):
                rc, err = self.call(c)
                self.assertEqual(rc, 2, err)
                self.assertIn("[auto-flow guard]", err)

    def test_running_allowed(self):
        self.fx.write_state("running"); self.fx.clear_gate()
        for c in ALLOW_RUNNING:
            with self.subTest(c=c):
                self.assertEqual(self.call(c)[0], 0)
        self.assertEqual(self.call("gh pr merge 1 --merge", tool="Read")[0], 0)

    def test_gh_pr_merge_with_gate(self):
        self.fx.write_state("running"); self.fx.write_gate()
        self.assertEqual(self.call("gh pr merge 1 --merge")[0], 0)
        self.fx.write_gate(drop=("G8",))
        self.assertEqual(self.call("gh pr merge 1 --merge")[0], 2)
        self.fx.clear_gate()

    def test_corrupt_state(self):
        self.fx.write_state(raw='{"status": "running", ')
        self.assertEqual(self.call("gh pr merge 1")[0], 2)
        self.assertEqual(self.call("ls")[0], 0)
        self.fx.write_state("completed")

    def test_bad_stdin(self):
        r = subprocess.run([sys.executable, AF_GUARD], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
