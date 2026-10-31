#!/usr/bin/env bash
# Send an executor's task back with verification findings, in its existing worktree and branch.
# Usage: bounce.sh <slug> <model> <task-brief.md> <findings.md>
# Same environment variables as launch.sh. The chain re-checks and re-merges the branch when the run exits.
set -euo pipefail
slug="$1"; model="$2"; brief="$3"; findings="$4"
repo="${AIO_REPO:-$(git rev-parse --show-toplevel)}"
name=$(basename "$repo")
wtroot="${AIO_WTROOT:-$(dirname "$repo")/.worktrees/$name}"
dir="${AIO_EXEC_DIR:-$repo/.tmp/executors}"
integration="${AIO_INTEGRATION:-integration}"
wt="$wtroot/$slug"
[ -d "$wt" ] || { echo "no worktree $wt" >&2; exit 1; }
screen -ls | grep -q "agent-$name-$slug\b" && { echo "already running" >&2; exit 1; }
n=$( (ls "$dir/$slug".status* 2>/dev/null || true) | wc -l)
[ -f "$dir/$slug.status" ] && mv "$dir/$slug.status" "$dir/$slug.status.$n"
{
  cat "$dir/brief-common.md" "$dir/$brief"
  cat <<EOF

## BOUNCE: independent verification failed, fix it in this same worktree and branch

Your previous commit was merged into \`$integration\` and then reviewed by an independent verifier, who BOUNCED it.

1. \`git merge $integration\` into your branch first (no rebase); resolve conflicts preserving both sides' intent.
2. Fix EVERY finding below; add or strengthen a test for each. If you think a finding is wrong, keep the conservative behaviour and explain it under Open issues.
3. Run the tests named in your brief; commit as \`fix(<area>): address verification findings (<task id>)\`.
4. Append a "Bounce N" section to your Final Report: one line per finding (fixed: how / not fixed: why), tests, results.

### Findings
EOF
  cat "$findings"
} > "$dir/$slug.prompt-bounce.md"
echo running > "$dir/$slug.chain"
screen -dmS "agent-$name-$slug" env SHELL=/bin/bash bash -lc "cd '$wt' && kilo run --auto --model '$model' --title '$name $slug bounce' \"\$(cat '$dir/$slug.prompt-bounce.md')\" 2>&1 | tee -a '$dir/$slug.log'; echo \"EXIT=\${PIPESTATUS[0]} \$(date -Is)\" >> '$dir/$slug.status'"
echo "bounced $slug ($model)"
