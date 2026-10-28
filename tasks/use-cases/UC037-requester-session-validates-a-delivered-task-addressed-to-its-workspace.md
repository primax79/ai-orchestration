# UC037 - Requester session validates a delivered task addressed to it

- id: UC037
- title: Requester session validates a delivered task addressed to it
- actor: Requester session
- approval: proposed
- priority: P1
- linked-tasks: T044, T047
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Requester verifies task

## Description & Business Value
Allows a delivered task to carry a durable verification request (verify-by: workspace:<slug> or session:<id>) with an explicit verification check so the requesting project's session can discover it in its verification queue and transition it to verified or bounced. Source: tasks/specs/task-and-state-model.md §3

## Preconditions
- A task requested by another workspace/session reaches delivered state with --verify-by set.

## Scenario / Interaction Steps
1. Upon delivery, the task sets --verify-by workspace:<requester> and --verify-check "<check>".
2. The requester session runs ai-orch tasks verification-queue --for <requester> and sees the delivered item with its check instructions.
3. After testing the feature in its own workspace, the requester session transitions the task to verified (or bounced with findings).

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Requested feature" --short "Requested feature" --priority P1 --priority-reason "Requested" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks transition T001 delivered --tasks-dir "$T/tasks" --verify-by "workspace:gcube_atlas" --verify-check "Run atlas CLI check" >/dev/null && ./bin/ai-orch tasks verification-queue --tasks-dir "$T/tasks" --for gcube_atlas --json | jq -e "(.items | length == 1) and (.items[0].id == \"T001\")" >/dev/null && ./bin/ai-orch tasks transition T001 verified --tasks-dir "$T/tasks" --verifier "workspace:gcube_atlas" --actor gcube_atlas --json | jq -e ".ok == true and .new_state == \"verified\"" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks set-verify-by` (or `transition <id> delivered --verify-by <target> --verify-check <text>`) stores the durable verification request target on the task.
- [ ] `ai-orch tasks verification-queue --for <target>` lists all delivered tasks awaiting verification by that workspace or session.
- [ ] When no external user session exists, the architect can verify delivered items directly (T047).

## AI Validation Log

