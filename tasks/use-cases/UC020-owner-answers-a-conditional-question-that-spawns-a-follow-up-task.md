# UC020 - Owner answers a conditional question that spawns a follow-up task

- id: UC020
- title: Owner answers a conditional question that spawns a follow-up task
- actor: Owner
- approval: proposed
- priority: P2
- linked-tasks: T030, T031
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Answer conditional question

## Description & Business Value
Supports non-blocking conditional decisions (conditions: Q###) on finished tasks and automatically spawns a linked follow-up task when the owner answers the question with --changes-result. Source: tasks/specs/blocking-questions.md §0.Q12

## Preconditions
- A finished task lists an open question Q### in its conditions: header.

## Scenario / Interaction Steps
1. A task completes with a provisional choice and records conditions: Q###.
2. The owner reviews Q### and answers it with --changes-result because the chosen option alters the completed work.
3. The engine resolves the condition on the finished task and creates a new follow-up task linked to both the original task and Q###.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Finished task" --short "Finished task" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch questions ask --tasks-dir "$T/tasks" --question "Should timeout default to 30s or 60s?" --context "Picked 30s provisionally." --option "A=30s: faster fail" --option "B=60s: safer on slow CI" --recommended A --blocks "-" --decider owner --asked-by "kilo:bulk-execution" >/dev/null && sed -i "" "s/- short: Finished task/- conditions: Q001\n- short: Finished task/" "$T/tasks/engine/T001-finished-task.md" && ./bin/ai-orch tasks close T001 --tasks-dir "$T/tasks" --verifier "claude:deep-reasoning" --actor claude >/dev/null && ./bin/ai-orch questions answer Q001 --tasks-dir "$T/tasks" --choice B --text "Use 60s" --by owner --changes-result --json | jq -e ".ok == true and (.conditions_resolved | length == 1) and (.follow_up_tasks | length == 1)" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Tasks with unresolved `conditions: Q###` report `conditional: true` and appear in the `## Conditional` index table with question age and decider.
- [ ] `ai-orch questions answer Q### --changes-result` lists resolved conditional tasks in `conditions_resolved` and automatically creates a follow-up task with `sources: <task_id>, <question_id>`.
- [ ] Once all condition questions on a finished task are answered, the task moves from `## Conditional` to `## Done` on the next `sync-index`.

## AI Validation Log

