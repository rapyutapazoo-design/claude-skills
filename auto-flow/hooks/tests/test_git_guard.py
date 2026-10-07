"""層1（Git フック）を実 git で検証する。判定は main と bare リモートの実際の値で行う。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _util import ConfigModeMixin, ShimModeMixin, Fixture, WORK  # noqa: E402

TAG = "[auto-flow guard]"

# (コマンド, 'local'|'remote')。拒否時は main と remote main の両方が不変であること。
DENY_CASES = [
    ("git rebase %s main" % WORK, "local"),
    ("git checkout -qB main %s" % WORK, "local"),
    ("git switch --force-create main %s" % WORK, "local"),
    ("git switch -q main && git pull --no-rebase . %s:main" % WORK, "local"),
    ("git fetch . %s:main" % WORK, "local"),
    ("git switch -q main; if true; then git merge %s; fi" % WORK, "local"),
    ("git switch -q main; bash <<'EOF'\ngit merge %s\nEOF" % WORK, "local"),
    ("# user's note\ngit push origin %s:main" % WORK, "remote"),
    ("git switch -q main && git commit -m 'docs: `x` $(y)' --allow-empty", "local"),
    ("git switch -q main && git merge --ff-only %s" % WORK, "local"),
    ("git switch -q main && git merge --no-ff -m m %s" % WORK, "local"),
    ("git switch -q main && git commit --allow-empty --no-verify -m d", "local"),
    ("git switch -q main && git reset --hard %s" % WORK, "local"),
    ("git branch -f main %s" % WORK, "local"),
    ("git update-ref refs/heads/main $(git rev-parse %s)" % WORK, "local"),
    ("git update-ref -d refs/heads/main", "local"),
    ("git branch -D main", "local"),
    ("git branch tmpb %s && git branch -M tmpb main" % WORK, "local"),
    ("git push origin :main", "remote"),
    ("git push origin +%s:main" % WORK, "remote"),
    ("git switch -q main && git revert --no-edit HEAD", "local"),
    ("git switch -q main && git cherry-pick %s" % WORK, "local"),
]

# 非実行時に全部成功するもの（push :main はリモート自身が拒否するため除外）
ALLOW_CASES = [c for c in DENY_CASES if c[0] != "git push origin :main"]


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


class GuardTests(_Base):
    def test_running_no_gate_denied(self):
        fx = self.fx
        for cmd, _ in DENY_CASES:
            with self.subTest(cmd=cmd):
                fx.reset_main()
                rc, out, err = fx.sh(cmd)
                self.assertNotEqual(rc, 0, err)
                self.assertEqual(fx.rev("main"), fx.m0)
                self.assertEqual(fx.remote_rev(), fx.m0)
                self.assertIn(TAG, err)

    def test_symbolic_ref_main_denied(self):
        fx = self.fx
        fx.sh("git symbolic-ref refs/heads/main refs/heads/%s" % WORK)
        self.assertEqual(fx.rev("main"), fx.m0)
        rc, out, err = fx.sh("git symbolic-ref -q refs/heads/main")
        self.assertNotEqual(rc, 0)  # symref になっていない

    def test_not_running_all_succeed(self):
        fx = self.fx
        for status in ("none", "completed"):
            for cmd, kind in ALLOW_CASES:
                with self.subTest(status=status, cmd=cmd):
                    fx.reset_main(running=False)
                    if status == "none":
                        os.remove(os.path.join(fx.run_dir, "state.json"))
                    rc, out, err = fx.sh(cmd)
                    self.assertEqual(rc, 0, err)
                    if kind == "local":
                        self.assertNotEqual(fx.rev("main"), fx.m0)
                    else:
                        self.assertNotEqual(fx.remote_rev(), fx.m0)

    def test_gate_pass_allows(self):
        fx = self.fx
        # ff
        fx.reset_main(); fx.write_gate()
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main"), fx.w0)
        # ff -> push
        rc, _, err = fx.sh("git push -q origin main")
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.remote_rev(), fx.w0)
        # no-ff
        fx.reset_main(); fx.write_gate()
        rc, _, err = fx.sh("git switch -q main && git merge --no-ff -m m %s" % WORK)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main^2"), fx.w0)
        # no-ff -> push
        rc, _, err = fx.sh("git push -q origin main")
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.remote_rev(), fx.rev("main"))

    def test_gate_invalid_denied(self):
        fx = self.fx
        cases = {
            "stale_head": None,
            "g8_missing": dict(drop=("G8",)),
            "g8_false": dict(checks={"G8": {"pass": False, "evidence": "x"}}),
            "schema1": dict(schema_version=1),
            "decision_pr": dict(decision="pr"),
            "passed_false": dict(passed=False),
            "run_id_mismatch": dict(run_id="other"),
        }
        for name, over in cases.items():
            with self.subTest(name=name):
                fx.reset_main()
                fx.write_gate(**(over or {}))
                if over is None:
                    rc, _, err = fx.sh("git commit -q --allow-empty -m more")
                    self.assertEqual(rc, 0, err)  # 作業ブランチへのコミットは常に可
                rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
                self.assertNotEqual(rc, 0)
                self.assertEqual(fx.rev("main"), fx.m0)

    def test_gate_pass_but_rewrite_denied(self):
        fx = self.fx
        fx.reset_main(); fx.write_gate()
        tree = "$(git hash-object -t tree -w --stdin </dev/null)"
        rc, _, err = fx.sh("git branch -f main $(git commit-tree %s -m orphan)" % tree)
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.m0)
        # head_sha を親に持つが、現在値の子孫ではない（巻き戻し・書き換え）
        fx.reset_main(running=False)
        rc, x, _ = fx.sh("git commit-tree %s -p %s -m x" % (
            "$(git rev-parse main^{tree})", fx.m0))
        x = x.strip()
        fx.sh("git update-ref refs/heads/main %s" % x)
        fx.write_state("running"); fx.write_gate()
        rc, _, err = fx.sh("git branch -f main $(git commit-tree %s -p %s -m y)" % (
            "$(git rev-parse %s^{tree})" % WORK, fx.w0))
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), x)

    def test_remote_sync_allowed(self):
        fx = self.fx
        rc, _, err = fx.sh("git commit -q --allow-empty -m r && git push -q origin main", cwd=fx.other)
        self.assertEqual(rc, 0, err)
        rr = fx.remote_rev()
        self.assertNotEqual(rr, fx.m0)
        rc, _, err = fx.sh("git switch -q main && git pull -q --ff-only")
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main"), rr)
        rc, _, err = fx.sh("git update-ref refs/heads/main %s" % fx.w0)
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), rr)

    def test_pack_refs_harmless(self):
        fx = self.fx
        fx.sh("git pack-refs --all")
        self.assertEqual(fx.rev("main"), fx.m0)
        self.assertEqual(fx.sh("git fsck --no-progress")[0], 0)
        self.assertEqual(fx.sh("git branch -f main main")[0], 0)

    def test_worktree_bypass_denied(self):
        fx = self.fx
        rc, _, err = fx.sh("git worktree add -q ../wt -b wt %s" % WORK)
        self.assertEqual(rc, 0, err)
        for cmd in ("git -C ../wt update-ref refs/heads/main %s" % fx.w0,
                    "git -C ../wt fetch . %s:main" % WORK):
            with self.subTest(cmd=cmd):
                rc, _, err = fx.sh(cmd)
                self.assertNotEqual(rc, 0)
                self.assertEqual(fx.rev("main"), fx.m0)

    def test_pre_commit_sensitive(self):
        fx = self.fx
        rc, _, err = fx.sh("echo K > .env && git add -f .env && git commit -qm x")
        self.assertNotEqual(rc, 0)
        self.assertIn(".env", err)
        self.assertEqual(fx.rev(WORK), fx.w0)
        fx.reset_main()
        rc, _, err = fx.sh("echo e > .env.example && git add .env.example && git commit -qm x")
        self.assertEqual(rc, 0, err)
        fx.reset_main(running=False)
        rc, _, err = fx.sh("echo K > .env && git add -f .env && git commit -qm x")
        self.assertEqual(rc, 0, err)

    def test_corrupt_state(self):
        fx = self.fx
        fx.write_state(raw='{"status": "running", ')
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.m0)
        fx.reset_main(); fx.write_state(raw='{"status": "running", ')
        rc, _, err = fx.sh("git commit -q --allow-empty -m w")
        self.assertNotEqual(rc, 0)  # 軽微1: running を示す破損 state では pre-commit も拒否
        self.assertEqual(fx.rev(WORK), fx.w0)
        fx.reset_main(); fx.write_state(raw="{broken")
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
        self.assertEqual(rc, 0, err)

    def test_probe_ref_always_denied(self):
        fx = self.fx
        fx.write_state("completed")
        rc, _, err = fx.sh("git update-ref refs/auto-flow-guard/probe HEAD")
        self.assertNotEqual(rc, 0)
        self.assertIn(TAG, err)

    # ---- レビュー3 追加 ----
    def test_A_unvetted_commits_denied(self):
        fx = self.fx
        # (1) ff 後に main へ追加コミット（親が head_sha の単一親コミット）
        fx.reset_main(); fx.write_gate()
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only %s" % WORK)
        self.assertEqual(rc, 0, err)
        rc, _, err = fx.sh("git commit -q --allow-empty -m extra")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.w0)
        # (2) side ブランチ経由の ff / push
        fx.reset_main(); fx.write_gate()
        fx.sh("git switch -q -c side %s && git commit -q --allow-empty -m s" % WORK)
        rc, _, err = fx.sh("git switch -q main && git merge --ff-only side")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.m0)
        rc, _, err = fx.sh("git push origin side:main")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.remote_rev(), fx.m0)
        # (3) head_sha を親に持つが現在値を親に持たない擬似マージ
        rc, _, err = fx.sh("git branch -f main $(git commit-tree $(git rev-parse side^{tree}) "
                           "-p %s -p side -m x)" % WORK)
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.m0)
        # (4) 正規の no-ff マージ（親 = 現在値 + head_sha）は引き続き通る
        fx.reset_main(); fx.write_gate()
        rc, _, err = fx.sh("git switch -q main && git merge --no-ff -m m %s" % WORK)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main^1"), fx.m0)

    def test_B_force_push_over_remote_denied(self):
        fx = self.fx
        fx.reset_main(); fx.write_gate()
        rc, _, err = fx.sh("git commit -q --allow-empty -m r && git push -q origin main", cwd=fx.other)
        self.assertEqual(rc, 0, err)
        r = fx.remote_rev()
        rc, _, err = fx.sh("git push -f origin %s:main" % WORK)  # リモートのコミットがローカルに無い
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.remote_rev(), r)
        fx.sh("git fetch -q origin")  # ローカルに取得しても、祖先でなければ拒否
        rc, _, err = fx.sh("git push -f origin %s:main" % WORK)
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.remote_rev(), r)

    def test_C_forged_tracking_ref_denied(self):
        fx = self.fx
        for cmd in ("git fetch -q . %s:refs/remotes/origin/main && git switch -q main && "
                    "git merge --ff-only origin/main" % WORK,
                    "git remote add evil . && git fetch -q . %s:refs/remotes/evil/main && "
                    "git switch -q main && git merge --ff-only evil/main" % WORK,
                    "git remote add evil . && git fetch -q . %s:refs/remotes/evil/main && "
                    "git switch -q main && git branch --set-upstream-to=evil/main main && "
                    "git merge --ff-only evil/main" % WORK):
            with self.subTest(cmd=cmd):
                fx.reset_main()
                rc, _, err = fx.sh(cmd)
                self.assertNotEqual(rc, 0)
                self.assertEqual(fx.rev("main"), fx.m0)
                fx.sh("git remote remove evil")

    def test_C_remote_unreachable_denied_and_pull_ok(self):
        fx = self.fx
        rc, _, err = fx.sh("git commit -q --allow-empty -m r && git push -q origin main", cwd=fx.other)
        self.assertEqual(rc, 0, err)
        rr = fx.remote_rev()
        fx.sh("git fetch -q origin")
        try:
            fx.sh("git remote set-url origin '%s/nonexistent.git'" % fx.tmp)
            rc, _, err = fx.sh("git switch -q main && git merge --ff-only origin/main")
            self.assertNotEqual(rc, 0)
            self.assertEqual(fx.rev("main"), fx.m0)
        finally:
            fx.sh("git remote set-url origin '%s'" % fx.remote)
        rc, _, err = fx.sh("git pull -q --ff-only")  # 正規の pull は成功
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main"), rr)

    def test_E_git_dir_from_outside_denied(self):
        fx = self.fx
        gd = os.path.join(fx.repo, ".git")
        cmds = ("GIT_DIR='%s' git update-ref refs/heads/main %s" % (gd, fx.w0),
                "git --git-dir='%s' --work-tree='%s' update-ref refs/heads/main %s" % (gd, fx.repo, fx.w0),
                "cd '%s' && git --git-dir='%s' branch -f main %s" % (fx.tmp, gd, fx.w0))
        for cmd in cmds:
            with self.subTest(cmd=cmd):
                fx.reset_main()
                rc, _, err = fx.sh(cmd, cwd=fx.tmp)
                self.assertNotEqual(rc, 0)
                self.assertEqual(fx.rev("main"), fx.m0)
                self.assertIn(TAG, err)
        fx.reset_main(running=False)
        rc, _, err = fx.sh(cmds[0], cwd=fx.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main"), fx.w0)

    def _side(self, name, base, tree_of):
        self.fx.sh("git update-ref refs/heads/%s $(git commit-tree %s^{tree} -p %s -m %s)"
                   % (name, tree_of, base, name))

    def test_F_noff_after_ff_denied(self):
        fx = self.fx
        # ローカル: 正規 ff の後に --no-ff side（親=[head_sha, side]）
        fx.reset_main(); fx.write_gate()
        self._side("side", WORK, WORK)
        self.assertEqual(fx.sh("git switch -q main && git merge --ff-only %s" % WORK)[0], 0)
        rc, _, err = fx.sh("git merge --no-ff -m x side")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.w0)
        # push: ff 後の push は通る。その後ガード停止で作った --no-ff マージの push は拒否
        self.assertEqual(fx.sh("git push -q origin main")[0], 0)
        fx.write_state("completed")
        fx.sh("git merge --abort; git reset -q --hard")
        self.assertEqual(fx.sh("git merge --no-ff -q -m x side")[0], 0)
        merged = fx.rev("main")
        fx.write_state("running")
        rc, _, err = fx.sh("git push origin main")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.remote_rev(), fx.w0)
        self.assertNotEqual(merged, fx.w0)

    def test_F_octopus_denied(self):
        fx = self.fx
        fx.reset_main(); fx.write_gate()
        fx.sh("git switch -q -c side2 main && echo s > s.txt && git add s.txt && git commit -qm s2 "
              "&& git switch -q main")
        octo = ("git update-ref refs/heads/main $(git commit-tree %s^{tree} -p main -p %s -p side2 -m o)"
                % (WORK, WORK))
        rc, _, err = fx.sh(octo)  # 親=[現在値, head_sha, side2]
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.m0)
        # push（親=[リモート先端, head_sha, side2]）
        fx.write_state("completed")
        self.assertEqual(fx.sh(octo)[0], 0)
        self.assertEqual(len(fx.sh("git rev-list --parents -n1 main")[1].split()), 4)
        fx.write_state("running")
        rc, _, err = fx.sh("git push origin main")
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.remote_rev(), fx.m0)

    def test_G_config_injection_denied(self):
        fx = self.fx
        evil = os.path.join(fx.tmp, "evil.git")
        fx.sh("rm -rf '%s' && git clone -q --bare . '%s' && git --git-dir='%s' update-ref "
              "refs/heads/main %s" % (evil, evil, evil, fx.w0))
        for pre, c in (("", "git -c 'url.%s.insteadOf=%s' " % (evil, fx.remote)),
                       ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0='url.%s.insteadOf' "
                        "GIT_CONFIG_VALUE_0='%s' " % (evil, fx.remote), "git ")):
            with self.subTest(c=pre + c):
                fx.reset_main()
                rc, _, err = fx.sh("git switch -q main && %s%smerge --ff-only %s" % (pre, c, WORK))
                self.assertNotEqual(rc, 0)
                self.assertEqual(fx.rev("main"), fx.m0)

    def test_ignorecase_protected_name(self):
        fx = self.fx
        fx.sh("git config core.ignorecase true")
        try:
            rc, _, err = fx.sh("git update-ref refs/heads/MAIN %s" % fx.w0)
            self.assertNotEqual(rc, 0)
            self.assertEqual(fx.rev("main"), fx.m0)
        finally:
            fx.sh("git config --unset core.ignorecase")


class TestConfigMode(ConfigModeMixin, GuardTests, unittest.TestCase):
    def test_hooks_path_devnull_denied(self):
        fx = self.fx
        rc, _, err = fx.sh("git -c core.hooksPath=/dev/null update-ref refs/heads/main %s" % fx.w0)
        self.assertNotEqual(rc, 0)
        self.assertEqual(fx.rev("main"), fx.m0)


class TestShimMode(ShimModeMixin, GuardTests, unittest.TestCase):
    def test_hooks_path_devnull_bypasses_known_limit(self):
        # 既知の限界: shim は -c core.hooksPath=/dev/null で迂回される（層2の R3 で防ぐ）
        fx = self.fx
        rc, _, err = fx.sh("git -c core.hooksPath=/dev/null update-ref refs/heads/main %s" % fx.w0)
        self.assertEqual(rc, 0, err)
        self.assertEqual(fx.rev("main"), fx.w0)


if __name__ == "__main__":
    unittest.main()
