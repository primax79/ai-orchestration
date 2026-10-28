# UC033 - Owner views unified ready queue across all projects in a workspace

- id: UC033
- title: Owner views unified ready queue across all projects in a workspace
- actor: Owner
- approval: proposed
- priority: P1
- linked-tasks: 16.9, T040, T046, T048
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Workspace-wide ready queue

## Description & Business Value
Aggregates tasks across all projects of a multi-project workspace in the Common View and CLI (ai-orch tasks next --all-projects), displaying qualified IDs (project/ID), project chips, and per-project active counts while routing writes to each item's own project. Source: tasks/specs/ui-multi-project.md §2

## Preconditions
- A workspace contains two or more registered or discovered child projects with tasks/.

## Scenario / Interaction Steps
1. The owner selects All projects in the workspace switcher or runs ai-orch tasks next --workspace <ws> --all-projects.
2. The engine loads every child project task tree and merges their ready queues ordered by priority.
3. Each returned item carries its project slug and qualified_id (project/ID).

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/ws/proj-a" "$T/ws/proj-b" && H1=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --apply --expect-plan-hash "$H1" >/dev/null && H2=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-b/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-b/tasks" --apply --expect-plan-hash "$H2" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/ws/proj-a/tasks" --category engine --title "Task in A" --short "Task in A" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/ws/proj-b/tasks" --category engine --title "Task in B" --short "Task in B" --priority P2 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && WH=$(PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch workspace register "$T/ws" --id demo-ws --config-dir "$T/cfg" --json | jq -r .plan_hash) && PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch workspace register "$T/ws" --id demo-ws --config-dir "$T/cfg" --apply --expect-hash "$WH" >/dev/null && DH=$(PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch projects discover "$T/ws" --config-dir "$T/cfg" --json | jq -r .plan_hash) && PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch projects discover "$T/ws" --config-dir "$T/cfg" --apply --expect-hash "$DH" >/dev/null && AI_ORCHESTRATION_CONFIG="$T/cfg/orchestration.toml" ./bin/ai-orch tasks next --workspace "$T/ws" --all-projects --json | jq -e "(.ready_queue | length == 2)" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks next --workspace <ws> --all-projects` aggregates ready tasks across all registered or discovered projects in the workspace.
- [ ] Every item in the common workspace view carries its `project` slug and `qualified_id` (`project/ID`).
- [ ] Mutating actions initiated from the common view route writes strictly to the target item's own project `tasks/` tree.

## AI Validation Log

