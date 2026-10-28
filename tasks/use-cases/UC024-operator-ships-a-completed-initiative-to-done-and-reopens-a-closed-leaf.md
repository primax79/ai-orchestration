# UC024 - Operator ships a completed initiative and reopens a closed leaf

- id: UC024
- title: Operator ships a completed initiative and reopens a closed leaf
- actor: Operator (CLI)
- approval: proposed
- priority: P1
- linked-tasks: 11.4, 11.6, T051
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Ship and reopen tasks

## Description & Business Value
Separates closed work from open work at every level: moves closed child blocks to ## Closed, ships completed initiatives to tasks/done/NN-<slug>/ with a generated summary.md skeleton and rewritten links, and restores ancestors when a closed leaf is reopened. Source: tasks/specs/subtasks.md §6

## Preconditions
- An initiative has all of its leaf tasks closed.

## Scenario / Interaction Steps
1. Closing leaf 01.1 moves its block under ## Closed in plan.md.
2. The operator runs ai-orch tasks ship 01 with --expect-plan-hash; the engine generates summary.md, moves the folder to tasks/done/01-demo/, and rewrites relative links.
3. If a regression is found, running ai-orch tasks reopen 01.1 --reason "..." restores both the leaf and the parent initiative back to their open locations.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && mkdir -p "$T/tasks/01-demo" && printf "# 01 - Demo Initiative\n\n- **Short:** Demo initiative\n- **Executor:** kilo\n\n## Tasks\n\n### 01.1 - First task\n- **Status:** \`open\` · **Short:** First task\n- **Goal:** Goal 1\n- **Verification:** pytest\n" > "$T/tasks/01-demo/plan.md" && ./bin/ai-orch tasks close 01.1 --tasks-dir "$T/tasks" --verifier "claude:deep-reasoning" --actor claude >/dev/null && SH=$(./bin/ai-orch tasks ship 01 --tasks-dir "$T/tasks" --dry-run --json | jq -r .plan_hash) && ./bin/ai-orch tasks ship 01 --tasks-dir "$T/tasks" --expect-plan-hash "$SH" --json | jq -e ".ok == true" >/dev/null && test -f "$T/tasks/done/01-demo/summary.md" && RH=$(./bin/ai-orch tasks reopen 01.1 --reason "Regression found" --tasks-dir "$T/tasks" --dry-run --json | jq -r .plan_hash) && ./bin/ai-orch tasks reopen 01.1 --reason "Regression found" --tasks-dir "$T/tasks" --expect-plan-hash "$RH" --json | jq -e ".ok == true" >/dev/null && test -f "$T/tasks/01-demo/plan.md" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Closing an inline child block moves it under `## Closed` at the bottom of the same file.
- [ ] `ai-orch tasks ship NN` writes a `summary.md` skeleton, moves `tasks/NN-<slug>/` to `tasks/done/NN-<slug>/`, and rewrites relative Markdown links across `tasks/**`.
- [ ] `ai-orch tasks reopen <id> --reason <text>` transitions a closed leaf back to `open` and restores any archived parent folder or shipped initiative back to its active location.

## AI Validation Log

