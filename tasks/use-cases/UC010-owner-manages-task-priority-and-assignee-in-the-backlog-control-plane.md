# UC010 - Owner manages task priority and assignee in the backlog control plane

- id: UC010
- title: Owner manages task priority and assignee in the backlog control plane
- actor: Owner
- approval: proposed
- priority: P1
- linked-tasks: 05.1, 05.3
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Manage backlog priority

## Description & Business Value
Allows the owner to inspect the task backlog and update structured header fields (priority, priority-reason, executor/assignee) deterministically without breaking the on-disk Markdown grammar. Source: tasks/specs/orchestration-extension-spec.md §2

## Preconditions
- A project tasks/ directory contains at least one open task.

## Scenario / Interaction Steps
1. The owner views the task in the Backlog Manager or CLI.
2. The owner updates the task priority to P1 with a reason and changes the assigned executor to claude.
3. The underlying task Markdown file and JSON representation reflect the updated priority and executor.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Backlog item" --short "Backlog item" --priority P2 --priority-reason "Initial" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks set-priority T001 P1 --reason "Urgent" --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks set-executor T001 claude --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks show T001 --tasks-dir "$T/tasks" --json | jq -e ".task.priority == \"P1\" and .task.executor == \"claude\"" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks set-priority <id> <P0-P3> --reason <text>` updates both `priority` and `priority-reason` in the task header.
- [ ] `ai-orch tasks set-executor <id> <executor>` updates the `executor` field without altering surrounding header or body sections.
- [ ] On-disk Markdown files remain valid according to `ai-orch tasks validate`.

## AI Validation Log

