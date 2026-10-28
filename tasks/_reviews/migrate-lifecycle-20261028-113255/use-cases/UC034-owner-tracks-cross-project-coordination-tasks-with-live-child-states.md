# UC034 - Owner tracks cross-project coordination tasks with live child states

- id: UC034
- title: Owner tracks cross-project coordination tasks with live child states
- actor: Owner
- status: draft
- priority: P2
- linked-tasks: 16.4, 16.9
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Track coordination tasks

## Description & Business Value
Allows a coordination task in the workspace _workspace tree to reference child project tasks via coordinates: project/ID, resolving their live states and short titles read-only for the common workspace view without duplicating task content. Source: tasks/specs/ui-multi-project.md §3

## Preconditions
- A registered workspace has a _workspace coordination task with coordinates: <project>/<id>.

## Scenario / Interaction Steps
1. An architect authors a coordination task in _workspace with coordinates: proj-a/T001.
2. When T001 in proj-a transitions to in progress, querying the _workspace task list resolves coordinates read-only against proj-a.
3. The common workspace view and CLI output display proj-a/T001 with its live state (in progress) and short title.

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/ws/proj-a" && H0=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/tasks" --apply --expect-plan-hash "$H0" >/dev/null && H1=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --apply --expect-plan-hash "$H1" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/ws/proj-a/tasks" --category engine --title "Subproject task" --short "Subproject task" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/ws/proj-a/tasks" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/ws/tasks" --category engine --title "Coordinated release" --short "Coord release" --priority P1 --priority-reason "Coord" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && sed -i "" "s/- short: Coord release/- coordinates: proj-a\/T001\n- short: Coord release/" "$T/ws/tasks/engine/T001-coordinated-release.md" && WH=$(PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch workspace register "$T/ws" --id demo-ws --config-dir "$T/cfg" --json | jq -r .plan_hash) && PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch workspace register "$T/ws" --id demo-ws --config-dir "$T/cfg" --apply --expect-hash "$WH" >/dev/null && DH=$(PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch projects discover "$T/ws" --config-dir "$T/cfg" --json | jq -r .plan_hash) && PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch projects discover "$T/ws" --config-dir "$T/cfg" --apply --expect-hash "$DH" >/dev/null && AI_ORCHESTRATION_CONFIG="$T/cfg/orchestration.toml" ./bin/ai-orch tasks list --tasks-dir "$T/ws/tasks" --json | jq -e "(.emergent_tasks[0].coordinates[0].state == \"in progress\") and (.emergent_tasks[0].coordinates[0].short_title == \"Subproject task\")" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Coordination tasks in `_workspace` declare `coordinates: <project>/<id>, ...` in their header.
- [ ] `tasks list --json` and the UI common view resolve each coordinated reference read-only against the target project's `tasks/` tree, returning `{project, id, state, short_title}`.
- [ ] Validation warns if a `coordinates:` reference points to an unknown project or malformed ID.

## AI Validation Log

