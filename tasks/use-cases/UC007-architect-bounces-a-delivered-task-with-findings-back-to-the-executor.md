# UC007 - Architect bounces a delivered task with findings back to the executor

- id: UC007
- title: Architect bounces a delivered task with findings back to the executor
- actor: Architect session
- status: draft
- priority: P1
- linked-tasks: 02.1, 03.2
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Bounce delivered task

## Description & Business Value
When a delivered task fails its verification check, the architect transitions it to bounced with concrete findings (B1..Bn) recorded in its progress log so the executor session can resume and fix the defect. Source: tasks/specs/task-and-state-model.md §3

## Preconditions
- A task is in the delivered state awaiting verification.

## Scenario / Interaction Steps
1. The architect inspects the delivered task and finds a failing verification criterion.
2. The architect runs ai-orch tasks transition <id> bounced --reason "B1: ...".
3. The engine transitions the task to bounced and records the finding.
4. The executor resumes the task by transitioning it from bounced back to in progress.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(~/.local/bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ~/.local/bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ~/.local/bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Bounce test" --short "Bounce test" --priority P1 --priority-reason "Core" --executor kilo --goal "Test bounce" --step "Step 1" --verification "pytest" >/dev/null && ~/.local/bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" >/dev/null && ~/.local/bin/ai-orch tasks transition T001 delivered --tasks-dir "$T/tasks" >/dev/null && ~/.local/bin/ai-orch tasks transition T001 bounced --tasks-dir "$T/tasks" --reason "B1: missing unit test" --actor claude >/dev/null && ~/.local/bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" --json | jq -e ".ok == true and .new_state == \"in progress\"" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Transition `delivered -> bounced` records the failing findings (`--reason`) in the task progress log.
- [ ] A `bounced` task transitions back to `in progress` so the assigned executor session can address the findings.
- [ ] After fixing the issues, the task must pass through `delivered` again before verification.

## AI Validation Log

