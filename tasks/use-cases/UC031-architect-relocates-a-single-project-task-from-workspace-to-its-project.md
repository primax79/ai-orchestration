# UC031 - Architect relocates a single-project task from workspace to project

- id: UC031
- title: Architect relocates a single-project task from workspace to project
- actor: Architect session
- approval: proposed
- priority: P2
- linked-tasks: 16.4
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Move task to project

## Description & Business Value
Enforces the workspace placement rule (_workspace holds only cross-project coordination tasks) by warning when a workspace task touches a single project and allowing the architect to relocate it into the target project while leaving a moved-to pointer behind. Source: tasks/specs/orchestration-broker-mcp.md §1

## Preconditions
- A task in the workspace _workspace tree touches paths inside a single child project.

## Scenario / Interaction Steps
1. Validation warns that the task belongs in the child project.
2. The architect runs ai-orch tasks move T### --to-project <slug> (or --to-tasks-dir) with --expect-task-hash.
3. The engine creates the task in the target project tree with relative paths adjusted and rewrites the original workspace task as a moved pointer (moved-to: <proj>/T###).

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/ws/proj-a" && H1=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/tasks" --apply --expect-plan-hash "$H1" >/dev/null && H2=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --apply --expect-plan-hash "$H2" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/ws/tasks" --category engine --title "Single project task" --short "Single project" --priority P2 --priority-reason "Move test" --executor kilo --paths "proj-a/src" --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && MH=$(./bin/ai-orch tasks show T001 --tasks-dir "$T/ws/tasks" --json | jq -r .task.bundle_sha256) && ./bin/ai-orch tasks move T001 --tasks-dir "$T/ws/tasks" --to-tasks-dir "$T/ws/proj-a/tasks" --expect-task-hash "$MH" --json | jq -e ".ok == true" >/dev/null && ./bin/ai-orch tasks show T001 --tasks-dir "$T/ws/proj-a/tasks" --json | jq -e ".task.id == \"T001\"" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks validate` on a workspace tree warns when a task without `coordinates:` touches paths belonging to a single child project.
- [ ] `ai-orch tasks move <id> --to-project <slug>` (or `--to-tasks-dir`) allocates a valid task in the target project and rewrites the source task as a `state: moved` pointer with `moved-to: <proj>/<id>`.
- [ ] Qualified references `[workspace:][project/]ID` are parsed and canonicalized deterministically across CLI and broker tools.

## AI Validation Log

