# UC015 - Executor transitions a task safely with optimistic concurrency hash

- id: UC015
- title: Executor transitions a task safely with optimistic concurrency hash
- actor: Executor agent
- approval: proposed
- priority: P1
- linked-tasks: 06.10
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Hash-guarded task transition

## Description & Business Value
Serializes concurrent task mutations under an exclusive file lock (.ai-orch.lock) and verifies --expect-task-hash against the task bundle SHA256 before writing atomically. Source: tasks/specs/control-plane-safety.md §0.A9

## Preconditions
- A task exists in tasks/ and exposes bundle_sha256 in show/list output.

## Scenario / Interaction Steps
1. The caller reads the current bundle_sha256 of the task.
2. If a concurrent writer modifies the task first (causing a hash mismatch), ai-orch tasks transition --expect-task-hash refuses the write.
3. When the hash matches under the exclusive lock, the transition succeeds and writes atomically.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Lock test" --short "Lock test" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && (! ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" --expect-task-hash "0000000000000000" >/dev/null 2>&1) && TH=$(./bin/ai-orch tasks show T001 --tasks-dir "$T/tasks" --json | jq -r .task.bundle_sha256) && ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" --expect-task-hash "$TH" --json | jq -e ".ok == true" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Mutating commands acquire an exclusive `fcntl.flock` on `<tasks_dir>/.ai-orch.lock` for the full read-modify-write cycle.
- [ ] `tasks show --json` and `tasks list --json` expose `bundle_sha256` for every task.
- [ ] `tasks transition --expect-task-hash <hash>` refuses the mutation and leaves the file unchanged if the current bundle hash differs.

## AI Validation Log

