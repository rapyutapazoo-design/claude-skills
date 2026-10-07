"""install_guards.py の検証（実 git）。"""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import Fixture, WORK  # noqa: E402

EVENTS = ("reference-transaction", "pre-push", "pre-commit")
KEYS = {"ok", "action", "mode", "hooks_dir", "events", "chained", "probe", "git_version", "reason"}
MARK = "# auto-flow-guard shim v1"


class InstallBase(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.hooks = os.path.join(self.fx.repo, ".git", "hooks")

    def tearDown(self):
        self.fx.close()

    def write_hook(self, name, body, d=None):
        p = os.path.join(d or self.hooks, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + body)
        os.chmod(p, 0o755)
        return p

    def deny_main(self):
        fx = self.fx
        fx.write_state("running")
        rc, _, err = fx.sh("git update-ref refs/heads/main %s" % fx.w0)
        fx.write_state("completed")
        return rc != 0 and fx.rev("main") == fx.m0


class TestInstall(InstallBase):
    def test_install_ok_both_modes_and_json(self):
        for mode in ("config", "shim"):
            with self.subTest(mode=mode):
                fx = self.fx
                rc, r = fx.installer("install", mode)
                self.assertEqual(rc, 0, r)
                self.assertTrue(KEYS <= set(r), r)
                self.assertTrue(r["ok"])
                self.assertEqual(r["mode"], mode)
                self.assertEqual(r["probe"], "denied")
                self.assertTrue(self.deny_main())
                rc, r = fx.installer("uninstall")
                self.assertEqual(rc, 0, r)
                self.assertTrue(KEYS <= set(r))

    def test_auto_picks_config(self):
        rc, r = self.fx.installer("install", "auto")
        self.assertEqual((rc, r["mode"]), (0, "config"), r)

    def test_check_json_keys(self):
        rc, r = self.fx.installer("check")
        self.assertEqual(rc, 1)
        self.assertTrue(KEYS <= set(r))
        self.assertFalse(r["ok"])

    def test_idempotent_config(self):
        fx = self.fx
        fx.installer("install", "config")
        rc, r = fx.installer("install", "config")
        self.assertEqual(rc, 0, r)
        for ev in EVENTS:
            for key in ("event", "command"):
                rc, out, _ = fx.sh("git config --local --get-all hook.auto-flow-guard-%s.%s" % (ev, key))
                self.assertEqual(len(out.strip().splitlines()), 1, (ev, key, out))

    def test_idempotent_shim(self):
        fx = self.fx
        fx.installer("install", "shim")
        rc, r = fx.installer("install", "shim")
        self.assertEqual(rc, 0, r)
        for ev in EVENTS:
            self.assertEqual(read(os.path.join(self.hooks, ev)).count(MARK), 1)
        self.assertEqual([n for n in os.listdir(self.hooks) if n.endswith(".auto-flow-orig")], [])

    def test_shim_chains_existing_hooks_and_uninstall_restores(self):
        fx = self.fx
        log = os.path.join(fx.tmp, "refs.log")
        self.write_hook("pre-commit", "exit 1\n")
        self.write_hook("reference-transaction",
                        'n=$(wc -l | tr -d " "); echo "$1 $n" >> "%s"\n' % log)
        orig_pc = read(os.path.join(self.hooks, "pre-commit"))
        rc, r = fx.installer("install", "shim")
        self.assertEqual(rc, 0, r)
        self.assertEqual(sorted(r["chained"]), ["pre-commit", "reference-transaction"])
        rc, _, err = fx.sh("git commit -q --allow-empty -m x")
        self.assertNotEqual(rc, 0)  # 元フックの失敗が優先される
        open(log, "w").close()
        rc, _, err = fx.sh("git update-ref refs/heads/foo HEAD")
        self.assertEqual(rc, 0, err)
        lines = read(log).split("\n")
        self.assertTrue(any(l.startswith("prepared ") and int(l.split()[1]) >= 1 for l in lines), lines)
        self.assertTrue(self.deny_main())
        rc, r = fx.installer("uninstall", "shim")
        self.assertEqual(rc, 0, r)
        self.assertEqual(read(os.path.join(self.hooks, "pre-commit")), orig_pc)
        self.assertNotIn(MARK, read(os.path.join(self.hooks, "reference-transaction")))
        self.assertEqual([n for n in os.listdir(self.hooks) if n.endswith(".auto-flow-orig")], [])

    def test_config_coexists_with_hookdir(self):
        fx = self.fx
        marker = os.path.join(fx.tmp, "ran")
        self.write_hook("pre-commit", 'echo y >> "%s"\n' % marker)
        rc, r = fx.installer("install", "config")
        self.assertEqual(rc, 0, r)
        rc, _, err = fx.sh("git commit -q --allow-empty -m x")
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.exists(marker))
        self.assertTrue(self.deny_main())

    def _tracked_hooks(self):
        fx = self.fx
        d = os.path.join(fx.repo, "tracked-hooks")
        os.mkdir(d)
        self.write_hook("pre-commit", "exit 0\n", d)
        fx.sh("git add tracked-hooks && git commit -qm th && git config core.hooksPath tracked-hooks")
        fx.m0 = fx.rev(WORK)  # 作業ブランチ上の最新（main は不変）

    def test_tracked_hookspath(self):
        fx = self.fx
        self._tracked_hooks()
        before = read(os.path.join(fx.repo, "tracked-hooks", "pre-commit"))
        rc, r = fx.installer("install", "shim")
        self.assertEqual(rc, 1)
        self.assertFalse(r["ok"])
        self.assertIn("Git 管理下", r["reason"])
        self.assertEqual(read(os.path.join(fx.repo, "tracked-hooks", "pre-commit")), before)
        rc, r = fx.installer("install", "config")
        self.assertEqual(rc, 0, r)
        fx.m0 = fx.rev("main")
        self.assertTrue(self.deny_main())

    def test_untracked_hookspath_shim(self):
        fx = self.fx
        os.mkdir(os.path.join(fx.repo, ".untracked-hooks"))
        fx.sh("git config core.hooksPath .untracked-hooks")
        rc, r = fx.installer("install", "shim")
        self.assertEqual(rc, 0, r)
        self.assertTrue(r["hooks_dir"].endswith(".untracked-hooks"))
        self.assertTrue(has_marker(os.path.join(fx.repo, ".untracked-hooks", "reference-transaction")))
        self.assertTrue(self.deny_main())

    def test_global_hookspath_refused(self):
        fx = self.fx
        fx.sh("git config --file '%s' core.hooksPath '%s'" % (fx.env["GIT_CONFIG_GLOBAL"], self.hooks))
        rc, r = fx.installer("install", "shim")
        self.assertEqual(rc, 1)
        self.assertIn("共通", r["reason"])

    def test_check_detects_removal_and_no_probe_ref_left(self):
        fx = self.fx
        for mode in ("config", "shim"):
            with self.subTest(mode=mode):
                fx.installer("install", mode)
                rc, r = fx.installer("check")
                self.assertEqual((rc, r["ok"], r["probe"]), (0, True, "denied"), r)
                if mode == "config":
                    fx.sh("git config --local --remove-section hook.auto-flow-guard-reference-transaction")
                else:
                    os.remove(os.path.join(self.hooks, "reference-transaction"))
                rc, r = fx.installer("check")
                self.assertEqual(rc, 1)
                self.assertFalse(r["ok"])
                self.assertEqual(r["probe"], "not_denied")
                self.assertIsNone(fx.rev("refs/auto-flow-guard/probe"))
                fx.installer("uninstall")

    def test_uninstall_refused_while_running(self):
        fx = self.fx
        fx.installer("install", "config")
        fx.write_state("running")
        rc, r = fx.installer("uninstall")
        self.assertEqual(rc, 1)
        self.assertFalse(r["ok"])
        rc, r = fx.installer("check")
        self.assertTrue(r["ok"])
        fx.write_state("completed")
        rc, r = fx.installer("uninstall")
        self.assertEqual(rc, 0, r)
        rc, out, _ = fx.sh("git config --local --get-regexp 'hook.auto-flow-guard'")
        self.assertEqual(out.strip(), "")

    def test_not_a_repo(self):
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "install_guards.py"), "check", "--repo", self.fx.tmp],
            env=self.fx.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(json.loads(r.stdout)["ok"])


SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAltLayouts(unittest.TestCase):
    """重大2: separate-git-dir・.git シンボリックリンクでも running 中は main への更新を拒否する。"""

    def setUp(self):
        self.fx = Fixture()
        self.t = os.path.join(self.fx.tmp, "alt")
        os.makedirs(self.t)

    def tearDown(self):
        self.fx.close()

    def sh(self, cmd, cwd):
        return subprocess.run(["bash", "-c", cmd], cwd=cwd, env=self.fx.env, capture_output=True,
                              text=True, timeout=60)

    def check(self, wt, mode):
        fx = self.fx
        r = subprocess.run([sys.executable, os.path.join(SKILL_ROOT, "hooks", "install_guards.py"),
                            "install", "--repo", wt, "--mode", mode],
                           env=fx.env, capture_output=True, text=True, timeout=60)
        self.assertTrue(json.loads(r.stdout.strip().splitlines()[-1])["ok"], r.stdout + r.stderr)
        rd = os.path.join(wt, ".auto-flow", "RID")
        os.makedirs(rd)
        with open(os.path.join(rd, "state.json"), "w") as f:
            json.dump({"run_id": "RID", "status": "running", "base_branch": "main",
                       "work_branch": "w"}, f)
        r = self.sh("git commit -q --allow-empty -m blocked", wt)
        self.assertNotEqual(r.returncode, 0, "running 中の main コミットが通った")
        self.assertIn("[auto-flow guard]", r.stderr)
        with open(os.path.join(rd, "state.json"), "w") as f:
            json.dump({"run_id": "RID", "status": "completed"}, f)
        r = self.sh("git commit -q --allow-empty -m ok", wt)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_separate_git_dir_and_symlink(self):
        for mode in ("config", "shim"):
            with self.subTest(layout="separate", mode=mode):
                wt = os.path.join(self.t, "wt-" + mode)
                store = os.path.join(self.t, "store-" + mode, "proj", ".git")
                os.makedirs(os.path.dirname(store))
                self.sh("git init -q -b main --separate-git-dir '%s' '%s' && cd '%s' && "
                        "git commit -q --allow-empty -m c1" % (store, wt, wt), self.t)
                self.check(wt, mode)
            with self.subTest(layout="symlink", mode=mode):
                wt = os.path.join(self.t, "sl-" + mode)
                store = os.path.join(self.t, "slstore-" + mode, ".git")
                os.makedirs(os.path.dirname(store))
                self.sh("git init -q -b main '%s' && cd '%s' && git commit -q --allow-empty -m c1 && "
                        "mv .git '%s' && ln -s '%s' .git" % (wt, wt, store, store), self.t)
                self.check(wt, mode)


class TestRobustness(unittest.TestCase):
    """重大D・軽微2・軽微6。スキルの tempdir コピーを設置・改変する（本体は触らない）。"""

    def setUp(self):
        self.fx = Fixture()
        self.copy = os.path.join(self.fx.tmp, "skill copy")
        shutil.copytree(SKILL_ROOT, self.copy, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        self.inst = os.path.join(self.copy, "hooks", "install_guards.py")
        self.gg = os.path.join(self.copy, "hooks", "git_guard.py")
        self.log = os.path.join(self.fx.tmp, "witness.log")

    def tearDown(self):
        self.fx.close()

    def witness(self):
        with open(self.gg, "w") as f:
            f.write("import sys\nopen(%r,'a').write(sys.argv[1]+'\\n')\n" % self.log)

    def calls(self):
        return read(self.log).split() if os.path.exists(self.log) else []

    def test_passthrough_when_guard_missing(self):
        for mode in ("config", "shim"):
            for what in ("body", "dir", "python"):
                for status in ("completed", "running"):
                    with self.subTest(mode=mode, what=what, status=status):
                        fx = Fixture()
                        try:
                            self._passthrough(fx, mode, what, status)
                        finally:
                            fx.close()

    def _passthrough(self, fx, mode, what, status):
        copy = os.path.join(fx.tmp, "skill copy")
        shutil.copytree(SKILL_ROOT, copy, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        inst = os.path.join(copy, "hooks", "install_guards.py")
        py = sys.executable
        if what == "python":
            py = os.path.join(fx.tmp, "py-link")
            os.symlink(sys.executable, py)
        r = subprocess.run([py, inst, "install", "--repo", fx.repo, "--mode", mode], env=fx.env,
                           capture_output=True, text=True)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertTrue(out["ok"], out)
        fx.write_state(status)
        if what == "body":
            os.rename(os.path.join(copy, "hooks", "git_guard.py"), os.path.join(copy, "hooks", "gg.moved"))
        elif what == "dir":
            os.rename(copy, copy + ".moved")
        else:
            os.remove(py)
        if what != "python":
            # ガード不在 = 素通り。G8 は check が検出する
            rc, chk = fx.installer("check", mode)
            self.assertFalse(chk["ok"], chk)
            cmd = ("git commit -q --allow-empty -m x && git branch nb && "
                   "git update-ref refs/heads/main %s" % fx.w0)
            rc, _, err = fx.sh(cmd)
            self.assertEqual(rc, 0, err)
        else:
            # python が消えても command -v python3 で代替し、ガードは効き続ける
            rc, _, err = fx.sh("git commit -q --allow-empty -m x")
            self.assertEqual(rc, 0, err)
            rc, _, err = fx.sh("git update-ref refs/heads/main %s" % fx.w0)
            self.assertEqual(rc != 0, status == "running", err)

    def test_fast_path_skips_python_when_not_running(self):
        for mode in ("config", "shim"):
            with self.subTest(mode=mode):
                fx = self.fx
                self.witness()
                subprocess.run([sys.executable, self.inst, "install", "--repo", fx.repo, "--mode", mode],
                               env=fx.env, capture_output=True, text=True)
                for status in ("none", "completed"):
                    if status == "none":
                        p = os.path.join(fx.run_dir, "state.json")
                        if os.path.exists(p):
                            os.remove(p)
                    else:
                        fx.write_state("completed")
                    if os.path.exists(self.log):
                        os.remove(self.log)
                    rc, _, err = fx.sh("git commit -q --allow-empty -m x && git branch b%s%s && git tag t%s%s"
                                       % (mode, status, mode, status))
                    self.assertEqual(rc, 0, err)
                    self.assertEqual(self.calls(), [], status)
                # 実行中・破損は Python に委ねる（fail-open にしない）
                for raw in (None, '{"status": "running", '):
                    fx.write_state("running", raw=raw)
                    if os.path.exists(self.log):
                        os.remove(self.log)
                    fx.sh("git branch r%s%s" % (mode, len(str(raw))))
                    self.assertIn("reference-transaction", self.calls())
                fx.installer("uninstall", mode)

    def test_probe_ignores_global_signing(self):
        fx = self.fx
        with open(fx.env["GIT_CONFIG_GLOBAL"], "w") as f:
            f.write("[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = /nonexistent/gpg\n")
        rc, r = fx.installer("install", "auto")
        self.assertEqual((rc, r["mode"]), (0, "config"), r)


def read(p):
    with open(p) as f:
        return f.read()


def has_marker(p):
    try:
        return MARK in read(p)
    except Exception:
        return False


if __name__ == "__main__":
    unittest.main()
