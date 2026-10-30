#!/usr/bin/env bash
# Launch one headless Kilo executor in GNU screen on a fresh git worktree.
# Usage: launch.sh <slug> <model> <task-brief.md> [base-branch]
# Environment (defaults suit the agents user on the hub):
#   AIO_REPO      repository clone            (default: /srv/agents/<repo of $PWD>, else $PWD)
#   AIO_WTROOT    worktrees root               (default: <parent of repo>/.worktrees/<repo name>)
#   AIO_EXEC_DIR  briefs, prompts, logs, status (default: $AIO_REPO/.tmp/executors, git-excluded)
set -euo pipefail
slug="$1"; model="$2"; task_file="$3"; base="${4:-main}"
repo="${AIO_REPO:-$(git rev-parse --show-toplevel)}"
name=$(basename "$repo")
wtroot="${AIO_WTROOT:-$(dirname "$repo")/.worktrees/$name}"
dir="${AIO_EXEC_DIR:-$repo/.tmp/executors}"
wt="$wtroot/$slug"; branch="kilo/$slug"; prompt="$dir/$slug.prompt.md"

[[ "$slug" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "invalid slug" >&2; exit 1; }
[ -e "$wt" ] && { echo "worktree exists: $wt" >&2; exit 1; }
screen -ls | grep -q "\.agent-$name-$slug\s" && { echo "screen session exists" >&2; exit 1; }
mkdir -p "$dir" "$wtroot"

git -C "$repo" worktree add -q -b "$branch" "$wt" "$base"
cat "$dir/brief-common.md" "$task_file" > "$prompt"
# SHELL is forced: Kilo runs its tool commands with $SHELL, which must exist on this host.
screen -dmS "agent-$name-$slug" env SHELL=/bin/bash bash -lc "cd '$wt' && kilo run --auto --model '$model' --title '$name $slug' \"\$(cat '$prompt')\" 2>&1 | tee -a '$dir/$slug.log'; echo \"EXIT=\${PIPESTATUS[0]} \$(date -Is)\" >> '$dir/$slug.status'"
echo "started agent-$name-$slug in $wt on $branch ($model, base $base)"
