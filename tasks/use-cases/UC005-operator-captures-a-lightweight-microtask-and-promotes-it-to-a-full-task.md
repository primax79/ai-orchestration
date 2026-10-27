# UC005 - Operator captures a microtask and promotes it to a full task

- id: UC005
- title: Operator captures a microtask and promotes it to a full task
- actor: Operator (CLI)
- status: draft
- priority: P2
- linked-tasks: 10.5, 03.2
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Create and promote microtask

## Description & Business Value
Captures a small bug or chore immediately as an XS microtask under tasks/micro/ and later promotes it in place to a full emergent task in a target category while preserving its T### identifier and dependency links. Source: tasks/specs/task-and-state-model.md §2.4

## Preconditions
- A valid tasks/ tree exists on disk.

## Scenario / Interaction Steps
1. The operator runs ai-orch tasks micro with title, kind, priority, and what description.
2. The engine writes tasks/micro/T###-<slug>.md with the reduced 8-field mandatory header.
3. When the work grows, the operator runs ai-orch tasks promote T### --category <cat>, converting it to a 13-field full task with Goal, Steps, and Verification sections.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks micro --tasks-dir "$T/tasks" --title "Fix typo in navbar" --kind fix --priority P3 --what "Fix label typo" >/dev/null && ./bin/ai-orch tasks promote T001 --tasks-dir "$T/tasks" --category engine --json | jq -e ".ok == true and (.file_path | contains(\"engine/T001-\"))" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks micro` creates `tasks/micro/T###-<slug>.md` with the 8 mandatory microtask fields (`id`, `title`, `kind`, `priority`, `state`, `executor`, `paths`, `depends-on`), `size: XS` default, and `## What` section.
- [ ] Microtask shares the global `T###` identifier space across active and `done/` directories.
- [ ] `ai-orch tasks promote <id> --category <cat>` moves the file into `tasks/<cat>/`, expands the header to the 13 core fields, and generates `## Goal`, `## Steps`, and `## Verification` while preserving the ID.

## AI Validation Log

