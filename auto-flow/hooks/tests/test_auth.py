"""起動認可: install_guards.py の認可処理・check と、validate_gate による Git フック／af_guard の拒否。"""
import json
import os
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import (AF_GUARD, INSTALL, RUN_ID, WORK, ConfigModeMixin, Fixture,  # noqa: E402
                   ShimModeMixin)

TAG = "[auto-flow guard]"


def iso(delta=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta)).isoformat()


def auth_dir(fx):
    return os.path.join(fx.repo, ".git", "auto-flow-auth")


class TestParseIso(unittest.TestCase):
    def test_formats(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import af_common as C
        base = C.parse_iso("2026-01-02T03:04:05+00:00")
        self.assertIsNotNone(base)
        for s in ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05+0000",
                  "2026-01-02T12:04:05+09:00", "2026-01-02T12:04:05+0900"):
            with self.subTest(s=s):
                self.assertEqual(C.parse_iso(s), base)
        for n in range(1, 10):
            s = "2026-01-02T03:04:05." + "5" * n + "Z"
            with self.subTest(frac=n):
                v = C.parse_iso(s)
                self.assertIsNotNone(v)
                self.assertAlmostEqual(v - base, float("0." + "5" * n), places=5)
        self.assertAlmostEqual(C.parse_iso("2026-01-02T12:04:05.123+0900") - base, 0.123, places=5)
        naive = C.parse_iso("2026-01-02T03:04:05")
        self.assertEqual(naive, datetime(2026, 1, 2, 3, 4, 5).timestamp())
        for bad in ("garbage", "", "2026-13-99T00:00:00Z", None, 5, "2026-01-02T03:04:05+9"):
            with self.subTest(bad=bad):
                self.assertIsNone(C.parse_iso(bad))


def records(fx):
    d = auth_dir(fx)
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


class TestInstallAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def setUp(self):
        fx = self.fx
        for d in (auth_dir(fx), os.path.dirname(fx.tokens_path("s"))):
            if os.path.isdir(d):
                for n in os.listdir(d):
                    os.remove(os.path.join(d, n))

    def test_token_authorizes(self):
        fx = self.fx
        tok = fx.put_token("sess")
        rc, r = fx.install_auth("sess", RUN_ID)
        self.assertEqual(rc, 0, r)
        self.assertTrue(r["ok"])
        self.assertTrue(r["authorized"], r)
        self.assertRegex(r["auth_id"], r"^[0-9a-f]{32}$")
        self.assertFalse(os.path.exists(tok))
        self.assertEqual(os.listdir(os.path.dirname(tok)), [])
        with open(os.path.join(auth_dir(fx), r["auth_id"] + ".json")) as f:
            rec = json.load(f)
        self.assertEqual((rec["run_id"], rec["session_id"]), (RUN_ID, "sess"))

    def test_no_token(self):
        fx = self.fx
        rc, r = fx.install_auth("sess", RUN_ID)
        self.assertEqual(rc, 0)
        self.assertTrue(r["ok"])
        self.assertFalse(r["authorized"])
        self.assertIn("起動トークンなし", r["auth_reason"])
        self.assertEqual(records(fx), [])

    def test_expired_and_future(self):
        fx = self.fx
        tok = fx.put_token("sess", age=601)
        rc, r = fx.install_auth("sess", RUN_ID)
        self.assertFalse(r["authorized"])
        self.assertFalse(os.path.exists(tok))  # 期限切れでも消費（削除）される
        tok = fx.put_token("sess", age=-120)
        rc, r = fx.install_auth("sess", RUN_ID)
        self.assertFalse(r["authorized"])
        self.assertFalse(os.path.exists(tok))
        self.assertEqual(records(self.fx), [])

    def test_other_session_token_untouched(self):
        fx = self.fx
        tok = fx.put_token("other")
        rc, r = fx.install_auth("sess", RUN_ID)
        self.assertFalse(r["authorized"])
        self.assertTrue(os.path.exists(tok))
        self.assertIn("他セッションの有効トークン: 1", r["auth_reason"])

    def test_token_not_reusable(self):
        fx = self.fx
        fx.put_token("sess")
        self.assertTrue(fx.install_auth("sess", RUN_ID)[1]["authorized"])
        self.assertFalse(fx.install_auth("sess", RUN_ID)[1]["authorized"])

    def test_missing_or_bad_args(self):
        fx = self.fx
        tok = fx.put_token("sess")
        rc, r = fx.install_auth(None, RUN_ID)
        self.assertEqual(rc, 0)
        self.assertFalse(r["authorized"])
        self.assertIn("session 未指定", r["auth_reason"])
        for rid in (None, "../x", "bad"):
            with self.subTest(run_id=rid):
                rc, r = fx.install_auth("sess", rid)
                self.assertFalse(r["authorized"])
                self.assertTrue(os.path.exists(tok))  # 消費されない
        rc, r = fx.install_auth("../x", RUN_ID)
        self.assertFalse(r["authorized"])
        self.assertTrue(os.path.exists(tok))

    def test_legacy_call_without_session(self):
        fx = self.fx
        rc, r = fx.installer("install", "config")
        self.assertEqual(rc, 0)
        self.assertFalse(r["authorized"])
        self.assertIn("session 未指定", r["auth_reason"])

    def test_linked_worktree_uses_common_dir(self):
        fx = self.fx
        wt = os.path.join(fx.tmp, "wt")
        rc, _, err = fx.sh("git worktree add -q -b wtb '%s'" % wt)
        self.assertEqual(rc, 0, err)
        try:
            fx.put_token("sess")
            rc, r = fx.install_auth("sess", RUN_ID, repo=wt)
            self.assertTrue(r["authorized"], r)
            self.assertTrue(os.path.isfile(os.path.join(auth_dir(fx), r["auth_id"] + ".json")))
            self.assertFalse(os.path.exists(os.path.join(wt, ".git", "auto-flow-auth")))
        finally:
            fx.sh("git worktree remove --force '%s'" % wt)

    def test_resume_replaces_old_record(self):
        fx = self.fx
        fx.put_token("sess")
        a1 = fx.install_auth("sess", RUN_ID)[1]["auth_id"]
        fx.put_token("sess")
        a2 = fx.install_auth("sess", RUN_ID)[1]["auth_id"]
        self.assertNotEqual(a1, a2)
        self.assertEqual(records(fx), [a2 + ".json"])

    def test_tokenless_install_deletes_old_record(self):
        fx = self.fx
        fx.put_token("sess")
        a1 = fx.install_auth("sess", RUN_ID)[1]["auth_id"]
        self.assertEqual(records(fx), [a1 + ".json"])
        rc, r = fx.install_auth("sess", RUN_ID)  # トークン無し
        self.assertFalse(r["authorized"])
        self.assertEqual(records(fx), [])
        # 期限切れトークンでも旧認可は失効している
        fx.put_token("sess")
        fx.install_auth("sess", RUN_ID)
        fx.put_token("sess", age=601)
        r = fx.install_auth("sess", RUN_ID)[1]
        self.assertFalse(r["authorized"])
        self.assertEqual(records(fx), [])

    def test_other_run_record_kept_on_failure(self):
        fx = self.fx
        fx.write_auth_record(auth_id="c" * 32, run_id="20260101-000000-other")
        fx.install_auth("sess", RUN_ID)
        self.assertEqual(records(fx), ["c" * 32 + ".json"])

    def test_check_reflects_state(self):
        fx = self.fx
        fx.put_token("sess")
        r = fx.install_auth("sess", RUN_ID)[1]
        fx.write_state("running", auth=False, auth_id=r["auth_id"])
        rc, c = fx.installer_check(RUN_ID)
        self.assertTrue(c["authorized"], c)
        self.assertEqual(c["auth_id"], r["auth_id"])
        fx.write_state("running", auth=False)
        rc, c = fx.installer_check(RUN_ID)
        self.assertFalse(c["authorized"])
        self.assertIn("起動認可なし", c["auth_reason"])
        rc, c = fx.installer_check(None)
        self.assertFalse(c["authorized"])


def _installer_check(self, run_id):
    args = [sys.executable, INSTALL, "check", "--repo", self.repo]
    if run_id:
        args += ["--run-id", run_id]
    r = subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=120)
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])


Fixture.installer_check = _installer_check


class _Base:
    MODE = None
    fx = None

    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()
        r = cls.fx.install(cls.MODE)
        assert r["ok"] and r["mode"] == cls.MODE and r["probe"] == "denied", r

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def setUp(self):
        self.fx.reset_main()

    def assert_denied(self, why=None):
        fx = self.fx
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
        self.assertNotEqual(rc, 0, why)
        self.assertEqual(fx.rev("main"), fx.m0, why)
        self.assertIn(TAG, err)
        self.assertIn("起動認可", err, why)
        fx.sh("git switch -q %s" % WORK)
        rc, _, err = fx.sh("git push origin %s:main" % WORK)
        self.assertNotEqual(rc, 0, why)
        self.assertEqual(fx.remote_rev(), fx.m0, why)
        self.assertIn("起動認可", err, why)


class AuthGateTests(_Base):
    def test_no_auth_denied(self):
        self.fx.write_state("running", auth=False)
        self.fx.write_gate()
        self.assert_denied("auth なし")

    def test_bad_auth_variants_denied(self):
        fx = self.fx

        def a_record_missing():
            fx.write_state("running", auth=False, auth_id="b" * 32)

        def b_other_run():
            fx.write_state("running")
            fx.write_auth_record(run_id="other")

        def c_started_late():
            fx.write_state("running", started_at=iso(660))

        def d_started_garbage():
            fx.write_state("running", started_at="garbage")

        def e_started_before_record():
            fx.write_state("running", started_at=iso(-3600))

        def f_token_too_old():
            fx.write_state("running")
            fx.write_auth_record(token_created_at=time.time() - 700)

        def g_no_session():
            fx.write_state("running")
            fx.write_auth_record(session_id="")

        def h_bad_id():
            fx.write_state("running", auth=False, auth_id="../../x")

        for fn in (a_record_missing, b_other_run, c_started_late, d_started_garbage,
                   e_started_before_record, f_token_too_old, g_no_session, h_bad_id):
            with self.subTest(case=fn.__name__):
                fx.reset_main()
                fn()
                fx.write_gate()
                self.assert_denied(fn.__name__)

    def test_tokenless_reinstall_revokes_old_auth(self):
        fx = self.fx
        fx.write_state("completed")
        fx.put_token("sess")
        rc, r = fx.install_auth("sess", RUN_ID, mode=self.MODE)
        self.assertTrue(r["authorized"], r)
        fx.write_state("stopped", auth=False, auth_id=r["auth_id"], started_at=iso(0))
        # トークン無しで同 run_id を再 install（誤起動での「再開」）
        rc, r2 = fx.install_auth("sess", RUN_ID, mode=self.MODE)
        self.assertFalse(r2["authorized"])
        # 旧 auth_id のまま running に戻しても拒否される
        fx.write_state("running", auth=False, auth_id=r["auth_id"], started_at=iso(0))
        fx.write_gate()
        self.assert_denied("旧認可レコード")

    def test_started_at_formats_allowed(self):
        fx = self.fx
        local = datetime.now().astimezone()
        for label, s in (("+0900", local.strftime("%Y-%m-%dT%H:%M:%S%z")),
                         ("utcZ", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))):
            with self.subTest(fmt=label):
                fx.reset_main()
                fx.write_state("running", started_at=s)
                fx.write_gate()
                rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
                self.assertEqual(rc, 0, err)

    def test_resumed_at_allows(self):
        fx = self.fx
        fx.write_state("running", started_at=iso(-3600), resumed_at=iso(0))
        fx.write_gate()
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main"), fx.w0)

    def test_real_install_flow_merges(self):
        fx = self.fx
        fx.write_state("completed")
        fx.put_token("sess")
        rc, r = fx.install_auth("sess", RUN_ID, mode=self.MODE)
        self.assertTrue(r["authorized"], r)
        fx.write_state("running", auth=False, auth_id=r["auth_id"], started_at=iso(0))
        fx.write_gate()
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s && git push -q origin main"
                           % WORK)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.remote_rev(), fx.w0)


class TestAuthConfigMode(ConfigModeMixin, AuthGateTests, unittest.TestCase):
    pass


class TestAuthShimMode(ShimModeMixin, AuthGateTests, unittest.TestCase):
    pass


class TestAfGuardAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fx = Fixture()

    @classmethod
    def tearDownClass(cls):
        cls.fx.close()

    def call(self, command):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": self.fx.repo}
        r = subprocess.run([sys.executable, AF_GUARD], input=json.dumps(payload), env=self.fx.env,
                           capture_output=True, text=True, timeout=30)
        return r.returncode, r.stderr

    def test_pr_merge_needs_auth(self):
        fx = self.fx
        fx.write_state("running", auth=False)
        fx.write_gate()
        rc, err = self.call("gh pr merge 1 --merge")
        self.assertEqual(rc, 2)
        self.assertIn("起動認可", err)
        fx.write_state("running")
        fx.write_gate()
        self.assertEqual(self.call("gh pr merge 1 --merge")[0], 0)
        fx.write_state("completed")

    def test_auth_files_protected_while_running(self):
        fx = self.fx
        fx.write_state("running")
        fx.clear_gate()
        for c in ("rm .git/auto-flow-auth/x.json",
                  "echo > ~/.claude/auto-flow/tokens/s.json",
                  "cp /dev/null .git/auto-flow-auth/x.json",
                  "mv ~/.claude/auto-flow/tokens/s.json /tmp/y"):
            with self.subTest(c=c):
                self.assertEqual(self.call(c)[0], 2)
        for c in ("cat .git/auto-flow-auth/x.json", "ls ~/.claude/auto-flow/tokens"):
            with self.subTest(c=c):
                self.assertEqual(self.call(c)[0], 0)
        fx.write_state("completed")


if __name__ == "__main__":
    unittest.main()
