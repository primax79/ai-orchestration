# UC019 - Agent files a blocking question and owner answers to unblock the task

- id: UC019
- title: Agent files a blocking question and owner answers to unblock the task
- actor: Owner
- approval: proposed
- priority: P1
- linked-tasks: 08.1, 08.2, 08.3, 08.4, 07.10
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Ask and answer question

## Description & Business Value
Allows an agent or session to file a structured blocking question (Q###) with labeled options and recommendation, putting blocked leaf tasks into waiting until the owner answers or withdraws the question, which automatically restores each task to its prior state. Source: tasks/specs/blocking-questions.md §3

## Preconditions
- A leaf task T### is in open or in progress state.

## Scenario / Interaction Steps
1. An agent files a question via ai-orch questions ask naming T### in --blocks.
2. The engine creates tasks/questions/Q###-<slug>.md, records T### (in progress) in blocks, and transitions T### to waiting with decider: Q###.
3. Direct transition out of waiting is refused while Q### remains open.
4. The owner answers Q### via ai-orch questions answer; T### automatically returns to in progress with decider reset to -.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Work item" --short "Work item" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch questions ask --tasks-dir "$T/tasks" --question "Which storage backend should we use?" --context "Need persistence." --option "A=SQLite: zero install" --option "B=Postgres: external server" --recommended A --blocks T001 --decider owner --asked-by "claude:orchestration" >/dev/null && ./bin/ai-orch tasks show T001 --tasks-dir "$T/tasks" --json | jq -e ".task.state == \"waiting\" and .task.fields.decider.value == \"Q001\"" >/dev/null && (! ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" >/dev/null 2>&1) && ./bin/ai-orch questions answer Q001 --tasks-dir "$T/tasks" --choice A --text "Use SQLite" --by owner >/dev/null && ./bin/ai-orch tasks show T001 --tasks-dir "$T/tasks" --json | jq -e ".task.state == \"in progress\" and .task.fields.decider.value == \"-\"" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch questions ask` reserves the next `Q###` via `O_EXCL` under the task lock and validates that `question` is <=160 chars and ends with `?`.
- [ ] Blocked tasks transition to `waiting` with `decider: Q###`, and prior state is stored in `blocks: T### (<prior_state>)`.
- [ ] `tasks transition` refuses to move a task out of `waiting` while any question in its `decider` remains open (unless `--force-unblock --reason` is used).
- [ ] `ai-orch questions answer` restores the task to its earliest recorded prior state once all linked questions are answered or withdrawn.

## AI Validation Log

