# UC023 - Architect decomposes a task into subtasks with inherited fields

- id: UC023
- title: Architect decomposes a task into subtasks with inherited fields
- actor: Architect session
- approval: proposed
- priority: P1
- linked-tasks: 11.1, 11.2, 11.3, 11.6, T035
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Decompose into subtasks

## Description & Business Value
Supports N-level task hierarchies (NN.T, NN.T.x, T###.x) where adding a child converts a leaf into an expanded container, children inherit Executor/Priority/Profile/Paths/Labels/Depends-on from ancestors, direct transitions on containers are refused, and container states are derived automatically. Source: tasks/specs/subtasks.md §1

## Preconditions
- An open initiative task or emergent task exists.

## Scenario / Interaction Steps
1. The architect previews and applies ai-orch tasks child add <parent> --title "..." with --expect-plan-hash.
2. The engine converts the parent leaf into a container and creates child <parent>.1 inheriting ancestor fields.
3. Direct transition on the container is refused, while transitioning the child leaf automatically updates the derived state of the container and initiative.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && mkdir -p "$T/tasks/01-demo" && printf "# 01 - Demo Initiative\n\n- **Short:** Demo initiative\n- **Executor:** kilo\n\n## Tasks\n\n### 01.1 - First task\n- **Status:** \`open\` · **Short:** First task\n- **Goal:** Goal 1\n- **Verification:** pytest\n" > "$T/tasks/01-demo/plan.md" && CH=$(./bin/ai-orch tasks child add 01.1 --title "Subtask A" --short "Subtask A" --tasks-dir "$T/tasks" --dry-run --json | jq -r .plan_hash) && ./bin/ai-orch tasks child add 01.1 --title "Subtask A" --short "Subtask A" --tasks-dir "$T/tasks" --expect-plan-hash "$CH" >/dev/null && ./bin/ai-orch tasks show 01.1.1 --tasks-dir "$T/tasks" --json | jq -e ".task.is_leaf == true and .task.fields.executor.value == \"kilo\" and .task.fields.executor.source == \"inherited:01\"" >/dev/null && (! ./bin/ai-orch tasks transition 01.1 "in progress" --tasks-dir "$T/tasks" >/dev/null 2>&1) && ./bin/ai-orch tasks transition 01.1.1 "in progress" --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks show 01.1 --tasks-dir "$T/tasks" --json | jq -e ".task.state == \"in progress\" and .task.is_container == true" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks child add <parent>` allocates the next `<parent>.<n>` ID (considering both open and closed children) and converts a leaf parent into a container.
- [ ] Child nodes inherit `Executor`, `Priority`, `Profile`, `Repo`, and `Paths` from the nearest ancestor that defines them, reporting `source: inherited:<id>`.
- [ ] Direct state transitions on containers are refused; container state is derived via the S5 total function over its children.
- [ ] `expand` and `collapse` round-trip inline `###` blocks and `<id>-<slug>/README.md` folders losslessly with `--expect-plan-hash`.

## AI Validation Log

