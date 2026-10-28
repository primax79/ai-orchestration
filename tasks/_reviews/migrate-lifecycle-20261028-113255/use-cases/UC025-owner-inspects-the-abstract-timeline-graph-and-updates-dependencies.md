# UC025 - Owner inspects the abstract timeline graph and updates dependencies

- id: UC025
- title: Owner inspects the abstract timeline graph and updates dependencies
- actor: Owner
- status: draft
- priority: P1
- linked-tasks: 10.1, 10.2, 10.3, 10.6
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Inspect timeline graph

## Description & Business Value
Computes the date-free abstract timeline (columns by dependency step, priority-ordered ready_queue in column 0, and size-weighted longest_chain) and lets the owner edit dependencies, priorities, and sizes while rejecting cycles. Source: tasks/specs/timeline-gantt.md §2

## Preconditions
- Open leaf tasks and microtasks exist in tasks/ with dependency links.

## Scenario / Interaction Steps
1. The owner runs ai-orch tasks graph --json (or opens the Timeline tab).
2. The engine places ready tasks (no open dependencies) in column 0 and dependent tasks in subsequent columns, and computes ready_queue and longest_chain.
3. When the owner edits dependencies via ai-orch tasks set-deps, any change that would introduce a dependency cycle is refused with the cycle path.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Task A" --short "Task A" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal A" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Task B" --short "Task B" --priority P2 --priority-reason "Next" --executor kilo --depends-on T001 --goal "Goal B" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks set-size T002 L --tasks-dir "$T/tasks" >/dev/null && (! ./bin/ai-orch tasks set-deps T001 --add T002 --tasks-dir "$T/tasks" >/dev/null 2>&1) && ./bin/ai-orch tasks graph --tasks-dir "$T/tasks" --json | jq -e "(.ready_queue == [\"T001\"]) and (.longest_chain == [\"T001\", \"T002\"]) and (.columns.T001 == 0) and (.columns.T002 == 1)" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks graph --json` computes `columns` (0 for ready tasks with no open dependencies), `ready_queue` (column-0 tasks ordered by priority, `next-up: yes`, then ID), and `longest_chain` weighted by task `size`.
- [ ] Container dependencies expand automatically to all leaf descendants of the container.
- [ ] `ai-orch tasks set-deps` refuses dependency additions that would create a cycle in the expanded graph and names the cycle path.
- [ ] `ai-orch tasks graph --mermaid` outputs a valid `flowchart LR` grouped by column.

## AI Validation Log

