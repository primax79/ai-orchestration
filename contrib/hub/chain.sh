#!/usr/bin/env bash
# Deterministic (no LLM) chaining of executors on the hub.
# For each executor that exits: require >=1 commit and a clean worktree, run the suite in its worktree
# (tolerating only failures already in the baseline), merge into the integration branch if green and
# clean, re-run the suite after the merge (undo it if red), then launch the tasks whose prerequisites
# are all merged. Never touches main, never pushes. Decisions are appended to chain.log.
#
# Task table: $AIO_EXEC_DIR/chain.tasks, one task per line (# comments allowed):
#   <slug> <model> <brief.md> <report-path-in-branch> <prereq-slug,...|->
# Environment: AIO_REPO, AIO_WTROOT, AIO_EXEC_DIR (as launch.sh), AIO_INTEGRATION (default integration),
#   AIO_SUITE (default: uvx --quiet --python 3.12 pytest -q -p no:cacheprovider), AIO_BASELINE (suite log of main),
#   AIO_MAX_PARALLEL (default 4).
set -uo pipefail
repo="${AIO_REPO:-$(git rev-parse --show-toplevel)}"
name=$(basename "$repo")
wtroot="${AIO_WTROOT:-$(dirname "$repo")/.worktrees/$name}"
dir="${AIO_EXEC_DIR:-$repo/.tmp/executors}"
integration="${AIO_INTEGRATION:-integration}"
suite="${AIO_SUITE:-uvx --quiet --python 3.12 pytest -q -p no:cacheprovider}"
baseline="${AIO_BASELINE:-$dir/baseline-tests.log}"
max_parallel="${AIO_MAX_PARALLEL:-4}"
int="$wtroot/integration"
log="$dir/chain.log"
here=$(cd "$(dirname "$0")" && pwd)

say() { echo "$(date -Is) $*" | tee -a "$log"; }
state() { cat "$dir/$1.chain" 2>/dev/null || echo ""; }
setstate() { echo "$2" > "$dir/$1.chain"; say "$1 -> $2"; }
running() { screen -ls | grep -c "agent-$name-"; }

declare -A model brief report prereq
order=()
while read -r s m b r p; do
  [[ -z "${s:-}" || "$s" == \#* ]] && continue
  model[$s]=$m; brief[$s]=$b; report[$s]=$r; prereq[$s]=${p//,/ }; [ "${prereq[$s]}" = "-" ] && prereq[$s]=""
  order+=("$s")
done < "$dir/chain.tasks"

# Green = exit 0, or every FAILED/ERROR test was already failing in the baseline.
suite_ok() {
  local where="$1" out="$2" new
  (cd "$where" && $suite > "$out" 2>&1) && return 0
  grep -qE '^(FAILED|ERROR) ' "$out" || return 1
  new=$(grep -E '^(FAILED|ERROR) ' "$out" | awk '{print $2}' | sort -u | comm -23 - <(grep -sE '^(FAILED|ERROR) ' "$baseline" | awk '{print $2}' | sort -u))
  [ -z "$new" ] && { say "$(basename "$out"): only baseline failures"; return 0; }
  say "$(basename "$out"): new failures: $(echo $new)"; return 1
}

process_done() {
  local s="$1" wt="$wtroot/$1" base
  base=$(git -C "$wt" merge-base HEAD "$integration")
  [ "$(git -C "$wt" rev-list --count "$base"..HEAD)" -eq 0 ] && { setstate "$s" "no-commit"; return; }
  [ -n "$(git -C "$wt" status --porcelain --untracked-files=no)" ] && { setstate "$s" "dirty-worktree"; return; }
  [ -f "$wt/${report[$s]}" ] || say "$s WARNING: no Final Report at ${report[$s]}"
  suite_ok "$wt" "$dir/$s.tests.log" || { setstate "$s" "tests-red"; return; }
  if ! git -C "$int" merge -q --no-ff -m "merge kilo/$s into $integration (chain, tests green)" "kilo/$s" >> "$log" 2>&1; then
    git -C "$int" merge --abort 2>/dev/null; setstate "$s" "merge-conflict"; return
  fi
  suite_ok "$int" "$dir/$s.post-merge-tests.log" || { git -C "$int" reset -q --hard ORIG_HEAD; setstate "$s" "post-merge-red-undone"; return; }
  setstate "$s" "merged"
}

[ -d "$int" ] || { git -C "$repo" worktree add -q "$int" "$integration" && say "integration worktree at $int"; }
say "chain started (${#order[@]} tasks)"
while true; do
  for s in "${order[@]}"; do
    st=$(state "$s")
    if [ -z "$st" ] && screen -ls | grep -q "agent-$name-$s\b"; then setstate "$s" running; st=running; fi
    if [ "$st" = running ] && [ -f "$dir/$s.status" ] && ! screen -ls | grep -q "agent-$name-$s\b"; then
      setstate "$s" checking; process_done "$s"
    fi
  done
  for s in "${order[@]}"; do
    [ -z "$(state "$s")" ] || continue
    ok=1; for p in ${prereq[$s]}; do [ "$(state "$p")" = merged ] || ok=0; done
    if [ $ok -eq 1 ] && [ "$(running)" -lt "$max_parallel" ]; then
      AIO_REPO="$repo" AIO_WTROOT="$wtroot" AIO_EXEC_DIR="$dir" "$here/launch.sh" "$s" "${model[$s]}" "$dir/${brief[$s]}" "$integration" \
        && setstate "$s" running || setstate "$s" launch-failed
    fi
  done
  active=0; pending=0
  for s in "${order[@]}"; do
    case "$(state "$s")" in running|checking) active=1;; "") ok=1; for p in ${prereq[$s]}; do case "$(state "$p")" in merged|running|checking|"") ;; *) ok=0;; esac; done; [ $ok -eq 1 ] && pending=1;; esac
  done
  [ $active -eq 0 ] && [ $pending -eq 0 ] && { say "chain idle: nothing running, nothing launchable; stopping"; break; }
  sleep 60
done
