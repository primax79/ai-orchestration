# UC006 - Executor delivers a task and closes it through an independent verifier

- id: UC006
- title: Executor delivers a task and closes it through an independent verifier
- actor: Executor agent
- approval: proposed
- priority: P1
- linked-tasks: 02.1, 03.2, T035
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Verify and close task

## Description & Business Value
Enforces the unified state machine guards: prevents skipping delivered, requires an independent verifier (verifier != executor) or explicit owner approval to enter verified, and archives the task into tasks/done/<category>/ upon reaching done. Source: tasks/specs/task-and-state-model.md §3

## Preconditions
- An emergent task T001 exists in state open with executor set to kilo.

## Scenario / Interaction Steps
1. The executor transitions T001 from open to in progress.
2. Attempting to transition directly from in progress to done is refused by the state machine.
3. The executor transitions T001 to delivered after completing work.
4. An independent verifier (claude:deep-reasoning) transitions T001 to verified, and it is then transitioned to done and moved under tasks/done/.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Guard test" --short "Guard test" --priority P1 --priority-reason "Core" --executor kilo --goal "Test guards" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" >/dev/null && (! ./bin/ai-orch tasks transition T001 done --tasks-dir "$T/tasks" >/dev/null 2>&1) && ./bin/ai-orch tasks transition T001 delivered --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks transition T001 verified --tasks-dir "$T/tasks" --verifier "claude:deep-reasoning" --actor claude >/dev/null && ./bin/ai-orch tasks transition T001 done --tasks-dir "$T/tasks" --json | jq -e ".ok == true and .new_state == \"done\"" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Direct transitions `open -> done` and `in progress -> done` are rejected by the state machine.
- [ ] Transition `delivered -> verified` requires an independent verifier (`verifier != executor`) or `--owner-approved`.
- [ ] Self-verification (`verification-mode: self` without independent verifier) cannot enter `verified` and closes as `done with a caveat: self-verified only`.
- [ ] Transition to `done` moves the task file into `tasks/done/<category>/` and updates `tasks/00-INDEX.md`.

## AI Validation Log

