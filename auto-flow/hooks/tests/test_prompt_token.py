"""prompt_token.py（UserPromptSubmit / UserPromptExpansion）。HOME を一時ディレクトリに隔離して実行する。"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import HOOKS  # noqa: E402

SCRIPT = os.path.join(HOOKS, "prompt_token.py")


class TestPromptToken(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="af tok "))
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = {k: v for k, v in os.environ.items() if k != "HOME"}
        self.env["HOME"] = self.home
        self.tdir = os.path.join(self.home, ".claude", "auto-flow", "tokens")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, payload, raw=None, env=None):
        inp = raw if raw is not None else json.dumps(payload)
        r = subprocess.run([sys.executable, SCRIPT], input=inp, env=env or self.env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr, "")
        return r

    def submit(self, prompt, event="UserPromptSubmit", sid="sess1", **extra):
        d = {"hook_event_name": event, "session_id": sid, "prompt": prompt, "cwd": "/x"}
        d.update(extra)
        return self.run_hook(d)

    def token(self, sid="sess1"):
        p = os.path.join(self.tdir, sid + ".json")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def test_issued(self):
        cases = [("自律実行してください: README を直す", "自律実行して"),
                 ("オートフローで X", "オートフロー"),
                 ("/auto-flow X", "auto-flow"),
                 ("AUTO-FLOW で", "auto-flow"),
                 ("ａｕｔｏ－ｆｌｏｗ で", "auto-flow"),
                 ("自動で最後まで進めて", "自動で最後まで進めて"),
                 ("全自動で進めて", "全自動で進めて")]
        for ev in ("UserPromptSubmit", "UserPromptExpansion"):
            for prompt, trig in cases:
                with self.subTest(ev=ev, prompt=prompt):
                    shutil.rmtree(self.tdir, ignore_errors=True)
                    self.submit(prompt, event=ev)
                    t = self.token()
                    self.assertIsNotNone(t)
                    self.assertEqual(t["session_id"], "sess1")
                    self.assertEqual(t["trigger"], trig)
                    self.assertEqual(t["event"], ev)
                    self.assertLessEqual(len(t["prompt_head"]), 200)
                    mode = stat.S_IMODE(os.stat(os.path.join(self.tdir, "sess1.json")).st_mode)
                    self.assertEqual(mode, 0o600)

    def test_created_iso_is_isoformat_with_colon_offset(self):
        from datetime import datetime
        self.submit("auto-flow X")
        t = self.token()
        dt = datetime.fromisoformat(t["created_iso"])
        self.assertIsNotNone(dt.tzinfo)
        self.assertRegex(t["created_iso"], r"[+-]\d{2}:\d{2}$")
        self.assertLess(abs(dt.timestamp() - t["created_at"]), 5)

    def test_prompt_head_truncated(self):
        self.submit("auto-flow " + "あ" * 500)
        self.assertEqual(len(self.token()["prompt_head"]), 200)

    def test_mention_still_issues_token_by_design(self):
        # 設計判断: トークンは起動語の文字列一致で発行する。言及・検討依頼での誤起動防止は
        # description と SKILL.md [0] の原文照合が担う（ソフト防御）。
        self.submit("auto-flow の改善を検討して")
        self.assertIsNotNone(self.token())

    def test_not_issued(self):
        cases = [
            dict(prompt="README を直して"),
            dict(prompt="自律的に考えて"),
            dict(prompt="<task-notification>auto-flow done</task-notification>"),
            dict(prompt="  <system-reminder>auto-flow</system-reminder>"),
            dict(prompt="<scheduled-task>auto-flow"),
            dict(prompt="auto-flow X", agent_id="sub1"),
            dict(prompt="auto-flow X", hook_event_name="PreToolUse"),
            dict(prompt="auto-flow X", session_id="../x"),
            dict(prompt="auto-flow X", session_id=""),
            dict(prompt="auto-flow X", session_id=None),
            dict(prompt="auto-flow X", session_id=123),
            dict(prompt=["auto-flow"]),
            dict(prompt=None),
        ]
        for over in cases:
            with self.subTest(over=over):
                d = {"hook_event_name": "UserPromptSubmit", "session_id": "sess1"}
                d.update(over)
                self.run_hook(d)
                self.assertFalse(os.path.exists(self.tdir) and os.listdir(self.tdir), over)
        d = {"hook_event_name": "UserPromptSubmit", "prompt": "auto-flow"}
        self.run_hook(d)  # session_id 欠落
        self.assertFalse(os.path.exists(self.tdir) and os.listdir(self.tdir))

    def test_bad_input(self):
        for raw in ("", "{broken", "[]", "null", '"auto-flow"'):
            with self.subTest(raw=raw):
                self.run_hook(None, raw=raw)
        self.assertFalse(os.path.exists(self.tdir))

    def test_failure_is_silent(self):
        f = os.path.join(self.tmp, "file")
        open(f, "w").close()
        env = dict(self.env, HOME=f)
        self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s",
                       "prompt": "auto-flow"}, env=env)

    def test_cleanup(self):
        os.makedirs(self.tdir)
        old = time.time() - 7200
        recent = time.time() - 300
        files = {"old.json": old, "x.json.consumed-1": old, "recent.json": recent}
        for n, t in files.items():
            p = os.path.join(self.tdir, n)
            open(p, "w").close()
            os.utime(p, (t, t))
        self.submit("auto-flow")
        left = set(os.listdir(self.tdir))
        self.assertEqual(left, {"recent.json", "sess1.json"})

    def test_reissue_overwrites(self):
        self.submit("auto-flow 1")
        t1 = self.token()["created_at"]
        time.sleep(0.05)
        self.submit("auto-flow 2")
        t2 = self.token()
        self.assertGreater(t2["created_at"], t1)
        self.assertIn("2", t2["prompt_head"])


if __name__ == "__main__":
    unittest.main()
