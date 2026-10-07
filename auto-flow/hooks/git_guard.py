#!/usr/bin/env python3
"""auto-flow Git フック本体（層1）。

使い方: git_guard.py <event> [hook args...]   event = reference-transaction | pre-push | pre-commit
.auto-flow/<ID>/state.json が running の間だけ、gate.json 合格前の保護ブランチ(main/master/base)
の ref 更新・push と、機密ファイルのコミットを exit 1 で拒否する。
出力は stderr のみ。フック内では ref を更新する git コマンドを呼ばない。
"""
import os
import signal
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import af_common as C  # noqa: E402

_running = {"v": False}

RECOVERY = ("復旧: rebase 中なら `git rebase --abort` / merge 中なら `git merge --abort` / "
            "ff マージ拒否後は `git reset --hard`（引数なし）")


def deny(msg, extra=True):
    sys.stderr.write("%s %s\n" % (C.GUARD_TAG, msg))
    if extra:
        sys.stderr.write("%s SKILL.md [7] のゲート判定後に再実行してください。%s\n%s\n"
                         % (C.GUARD_TAG, RECOVERY, C.ABORT_HINT))
    return 1


def read_lines(data):
    out = []
    for line in data.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            out.append(tuple(parts))
    return out


def head_ok(root, gate, sha, base):
    """sha が head_sha そのもの、または「親がちょうど2つで {base(更新前の値), head_sha} と一致し、
    base != head_sha の真のマージ」か（ff 後の --no-ff やオクトパスは不可）。"""
    h = gate["head_sha"]
    if sha == h:
        return True
    if not base or base == h:
        return False
    ps = C.parents(root, sha)
    return len(ps) == 2 and set(ps) == {base, h}


def ignorecase(root):
    rc, out = C.git(root, "config", "--get", "core.ignorecase")
    return rc == 0 and out.strip().lower() == "true"


def _ls_remote_env():
    env = dict(os.environ)
    for k in list(env):
        if k in C._STRIP_ENV or k in ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT") \
                or k.startswith("GIT_CONFIG_KEY_") or k.startswith("GIT_CONFIG_VALUE_"):
            env.pop(k)  # `git -c url.X.insteadOf=...` 等で ls-remote 先を偽装させない
    env["GIT_TERMINAL_PROMPT"] = "0"
    if "GIT_SSH_COMMAND" not in env:
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
    return env


def _ls_remote(root, remote, ref, timeout=15):
    """ls-remote を隔離して実行（stdin なし・新セッション・タイムアウトでプロセスグループごと kill）。"""
    try:
        p = subprocess.Popen(["git", "-C", root, "ls-remote", remote, ref],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, env=_ls_remote_env(),
                             start_new_session=True)
    except Exception:
        return None
    try:
        out, _ = p.communicate(timeout=timeout)
    except Exception:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            p.communicate(timeout=2)
        except Exception:
            pass
        return None
    return out if p.returncode == 0 else None


def remote_tip(root, branch):
    """base ブランチの upstream リモートの実際の先端(ls-remote)。取得できなければ None。"""
    rc, out = C.git(root, "config", "--get", "branch.%s.remote" % branch,
                    scrub_config=True)
    remote = out.strip() if rc == 0 and out.strip() else "origin"
    if remote == ".":
        return None
    out = _ls_remote(root, remote, "refs/heads/%s" % branch)
    if out is None:
        return None
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() == "refs/heads/%s" % branch:
            return sha.strip()
    return None


def ref_transaction(args, data):
    if not args or args[0] != "prepared":
        return 0
    lines = read_lines(data)
    for old, new, ref in lines:
        if ref == C.PROBE_REF and new != C.ZERO:
            return deny("機能プローブ ref の作成を拒否しました（ガードは有効です）", extra=False)
    cands = [l for l in lines if l[2].startswith("refs/heads/")]
    if not cands:
        return 0
    try:
        run = C.find_active_run(os.getcwd(), C.hook_extra_roots())
    except RuntimeError as e:
        defaults = set("refs/heads/" + b for b in C.PROTECTED_DEFAULT)
        if any(l[2].lower() in defaults for l in cands):
            return deny("状態ファイルを読めないため保護ブランチの更新を拒否します（%s）" % e)
        return 0
    if run is None:
        return 0
    _running["v"] = True
    prot = set("refs/heads/" + b for b in C.protected_branches(run))
    root = run["root"]
    ic = ignorecase(root)
    if ic:
        prot = set(p.lower() for p in prot)
    targets = [l for l in cands if (l[2].lower() if ic else l[2]) in prot]
    if not targets:
        return 0
    gate_reason, gate = C.validate_gate(run)
    for old, new, ref in targets:
        if new.startswith("ref:"):
            return deny("%s をシンボリック ref にする更新を拒否しました" % ref)
        rc, out = C.git(root, "rev-parse", "-q", "--verify", ref)
        cur = out.strip() if rc == 0 else None
        if new != C.ZERO and new == cur:
            continue  # no-op（pack-refs など）
        if new == C.ZERO:
            return deny("%s の削除を拒否しました（実行中は保護ブランチを削除できません）" % ref)
        reason = gate_reason
        if gate:
            if head_ok(root, gate, new, cur):
                if cur is None or C.is_ancestor(root, cur, new):
                    continue
                reason = "巻き戻し・履歴の書き換え（現在値の子孫ではない）"
            else:
                reason = "新しい値が gate.json の head_sha（または現在値と head_sha の真のマージ）ではない"
        # リモート同期: base の upstream リモートの実際の先端(ls-remote)と一致する ff だけ許可
        branch = ref[len("refs/heads/"):]
        if cur is None or C.is_ancestor(root, cur, new):
            tip = remote_tip(root, branch)
            if tip is not None and tip == new:
                continue
        return deny("%s の更新を拒否しました（理由: %s）" % (ref, reason))
    return 0


def pre_push(args, data):
    rows = []
    for line in data.splitlines():
        p = line.split(" ")
        if len(p) == 4 and p[2].startswith("refs/heads/"):
            rows.append(p)
    if not rows:
        return 0
    try:
        run = C.find_active_run(os.getcwd(), C.hook_extra_roots())
    except RuntimeError as e:
        defaults = set("refs/heads/" + b for b in C.PROTECTED_DEFAULT)
        if any(r[2].lower() in defaults for r in rows):
            return deny("状態ファイルを読めないため保護ブランチへの push を拒否します（%s）" % e)
        return 0
    if run is None:
        return 0
    _running["v"] = True
    prot = set("refs/heads/" + b for b in C.protected_branches(run))
    gate_reason, gate = C.validate_gate(run)
    root = run["root"]
    ic = ignorecase(root)
    if ic:
        prot = set(p.lower() for p in prot)
    for local_ref, local_sha, remote_ref, remote_sha in rows:
        if (remote_ref.lower() if ic else remote_ref) not in prot:
            continue
        if local_sha == C.ZERO:
            return deny("%s の削除 push を拒否しました" % remote_ref)
        if local_sha == remote_sha:
            continue
        if gate and head_ok(root, gate, local_sha, None if remote_sha == C.ZERO else remote_sha):
            if remote_sha == C.ZERO or C.is_ancestor(root, remote_sha, local_sha):
                continue
            return deny("%s への push を拒否しました（理由: リモートの先端がローカルの祖先ではない"
                        "＝他者のコミットを消す/未取得）" % remote_ref)
        return deny("%s への push を拒否しました（理由: %s）"
                    % (remote_ref, gate_reason or "push 内容が gate.json の head_sha（または"
                       "リモート先端と head_sha の真のマージ）ではない"))
    return 0


def pre_commit(args, data):
    try:
        run = C.find_active_run(os.getcwd(), C.hook_extra_roots())
    except RuntimeError as e:
        return deny("状態ファイルを読めないためコミットを拒否します（%s）" % e)
    if run is None:
        return 0
    _running["v"] = True
    rc, out = C.git(os.getcwd(), "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR",
                    keep_env=True)
    if rc != 0:
        return deny("ステージ済みファイルを取得できないためコミットを拒否します", extra=False)
    bad = [f for f in out.split("\0") if f and C.is_sensitive(f)]
    if bad:
        sys.stderr.write("%s 機密ファイルのコミットを拒否しました:\n" % C.GUARD_TAG)
        for f in bad:
            sys.stderr.write("  - %s\n" % f)
        sys.stderr.write("%s 対処: `git reset -q -- <file>` で外し、.gitignore に追加して再コミット\n"
                         % C.GUARD_TAG)
        return 1
    return 0


def main(argv):
    if len(argv) < 2:
        return 0
    event, args = argv[1], argv[2:]
    try:
        data = sys.stdin.read() if event != "pre-commit" else ""
    except Exception:
        data = ""
    try:
        if event == "reference-transaction":
            return ref_transaction(args, data)
        if event == "pre-push":
            return pre_push(args, data)
        if event == "pre-commit":
            return pre_commit(args, data)
        return 0
    except Exception as e:  # 実行中と確定後は fail-closed
        if _running["v"]:
            sys.stderr.write("%s 内部エラーのため拒否します（%s: %s）\n"
                             % (C.GUARD_TAG, type(e).__name__, e))
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
