# UC026 - Owner classifies and filters tasks by kind and labels across views

- id: UC026
- title: Owner classifies and filters tasks by kind and labels across views
- actor: Owner
- status: draft
- priority: P2
- linked-tasks: 10.4, 10.5
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Filter by kind and labels

## Description & Business Value
Allows assigning classification kind (feature, bug, fix, chore, docs, investigation) and free-form tags (labels) to tasks and filtering the backlog, Kanban, and timeline graph by kind and label combinations. Source: tasks/specs/timeline-gantt.md §6

## Preconditions
- Tasks exist in tasks/.

## Scenario / Interaction Steps
1. The owner sets task kind via ai-orch tasks set-kind and adds/removes tags via ai-orch tasks set-labels.
2. The owner queries active labels with counts via ai-orch tasks labels for autocomplete.
3. Filtering tasks list or tasks graph by --kind and --label returns matching nodes using AND across filter types and OR within the same filter.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Security fix" --short "Security fix" --priority P1 --priority-reason "Sec" --executor kilo --goal "Fix auth" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Docs update" --short "Docs update" --priority P3 --priority-reason "Docs" --executor kilo --goal "Update docs" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks set-kind T001 fix --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks set-labels T001 --add security regression --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks set-kind T002 docs --tasks-dir "$T/tasks" >/dev/null && ./bin/ai-orch tasks graph --tasks-dir "$T/tasks" --kind fix --label security --json | jq -e "(.nodes | length == 1) and (.nodes[0].id == \"T001\")" >/dev/null && ./bin/ai-orch tasks labels --tasks-dir "$T/tasks" --json | jq -e "(.labels | length == 2)" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch tasks set-kind` validates `kind` against the closed set (`feature`, `bug`, `fix`, `chore`, `docs`, `investigation`).
- [ ] `ai-orch tasks set-labels` validates tags against `[a-z0-9][a-z0-9-]*` (<=24 chars) and refuses removing inherited ancestor labels.
- [ ] `tasks list` and `tasks graph` support repeatable `--kind` and `--label` filters (OR within a field, AND across fields).
- [ ] `ai-orch tasks labels` returns all active labels with usage counts for UI autocomplete.

## AI Validation Log

