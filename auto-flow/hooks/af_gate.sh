#!/bin/sh
# auto-flow Git フックの入口。使い方: af_gate.sh <python> <event> [フック引数...]（stdin = git のフック入力）
# 1) ガード本体(git_guard.py)が無い・python が無い -> 素通り(exit 0)。G8 は install_guards.py check が検出する。
# 2) 非実行時の高速スキップ: 対象 ref が無い、または running の state.json が1つも無ければ Python を起動しない。
#    判定不能（git が失敗など）のときは必ず Python に委ねる（fail-open にしない）。
py="$1"; ev="$2"; shift 2
gg="$(dirname "$0")/git_guard.py"
[ -f "$gg" ] || exit 0
[ -x "$py" ] || py="$(command -v python3)" || exit 0
data=""; force=""
case "$ev" in
  reference-transaction)
    [ "$1" = prepared ] || exit 0
    data="$(cat)"
    case "$data" in
      *" refs/auto-flow-guard/"*) force=1 ;;  # 機能プローブは常に Python 判定（check の G8 検出用）
      *" refs/heads/"*) ;;
      *) exit 0 ;;
    esac ;;
  pre-push)
    data="$(cat)"
    case "$data" in *" refs/heads/"*) ;; *) exit 0 ;; esac ;;
esac
active=1
# 調べる候補 = 全 worktree + $PWD + show-toplevel（separate-git-dir・.git シンボリックリンク・core.worktree 対策）。
# 候補を確実に取れない（git 失敗・空）ときは active=1 のまま Python に委ねる。
c=""; top=""
if [ -z "$force" ]; then
  out="$(git rev-parse --path-format=absolute --git-common-dir --show-toplevel 2>/dev/null)" || out=""
  if [ -n "$out" ]; then
    c="$(printf '%s\n' "$out" | sed -n 1p)"; top="$(printf '%s\n' "$out" | sed -n 2p)"
  else
    c="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || c=""
  fi
fi
if [ -n "$c" ]; then
  if [ ! -d "$c/worktrees" ] && [ "${c##*/}" = ".git" ]; then
    wl="worktree ${c%/.git}"  # 追加 worktree が無い通常の repo は git を再起動しない
  else
    wl="$(unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR; git --git-dir="$c" worktree list --porcelain 2>/dev/null)" || wl=""
  fi
  if [ -n "$wl" ]; then
    active=0
    [ -n "$PWD" ] && wl="$wl
worktree $PWD"
    [ -n "$top" ] && wl="$wl
worktree $top"
    [ -n "$GIT_WORK_TREE" ] && wl="$wl
worktree $GIT_WORK_TREE"
    while IFS= read -r l; do
      case "$l" in
        "worktree "*)
          if grep -qs running "${l#worktree }"/.auto-flow/*/state.json 2>/dev/null; then active=1; fi ;;
      esac
    done <<EOF2
$wl
EOF2
  fi
fi
[ -z "$force" ] && [ "$active" = 0 ] && exit 0
if [ -n "$data" ]; then
  printf '%s\n' "$data" | "$py" "$gg" "$ev" "$@"
else
  "$py" "$gg" "$ev" "$@"
fi
exit $?
