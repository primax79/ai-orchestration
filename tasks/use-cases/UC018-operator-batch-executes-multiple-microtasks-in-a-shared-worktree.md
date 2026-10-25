# UC018 - Operator batch-executes multiple microtasks in a shared worktree

- id: UC018
- title: Operator batch-executes multiple microtasks in a shared worktree
- actor: Operator (CLI)
- status: draft
- priority: P2
- linked-tasks: 07.11
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Batch run microtasks

## Description & Business Value
Allows grouping multiple XS microtasks targeting the same repository into a single batch execute run in one shared worktree, requiring one commit prefixed by T### per microtask. Source: tasks/specs/agent-runs-from-ui.md §4

## Preconditions
- Two or more open microtasks exist targeting the same git repository.

## Scenario / Interaction Steps
1. The operator runs ai-orch run preview --batch T001,T002 --mode execute.
2. The engine verifies all microtasks resolve to the same repository and builds a combined batch prompt requiring one T###-prefixed commit per microtask.
3. When executed, the supervisor maps commits by T### prefix to each microtask independently.

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/repo" && git -C "$T/repo" init -q && git -C "$T/repo" config user.name "Test" && git -C "$T/repo" config user.email "test@example.com" && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks micro --tasks-dir "$T/repo/tasks" --title "Fix A" --kind fix --paths "tasks" --what "Fix A" >/dev/null && ./bin/ai-orch tasks micro --tasks-dir "$T/repo/tasks" --title "Fix B" --kind fix --paths "tasks" --what "Fix B" >/dev/null && git -C "$T/repo" add . && git -C "$T/repo" commit -q --no-verify -m "init" && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch config init-global >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch run preview --workspace "$T/repo" --batch "T001,T002" --mode execute --tool kilo --json | jq -e ".ok == true and .is_batch == true and (.batch_members | length == 2)" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `run preview --batch` and `run start --batch` accept comma-separated microtask IDs that resolve to a single repository.
- [ ] One shared worktree and branch `run/batch-<ids>` are created for the batch.
- [ ] The supervisor maps commits prefixed with `T###` to each microtask so `mark-delivered` can transition completed microtasks individually or as a batch.

## AI Validation Log

