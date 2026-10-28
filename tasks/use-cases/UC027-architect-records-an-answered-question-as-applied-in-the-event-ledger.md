# UC027 - Architect records an answered question as applied in the event ledger

- id: UC027
- title: Architect records an answered question as applied in the event ledger
- actor: Architect session
- approval: proposed
- priority: P1
- linked-tasks: 12.11, 12.12, T041
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Apply answered question

## Description & Business Value
Emits durable outbox-backed domain events for every task, question, inbox, run, and config mutation and tracks whether an answered question has been acted upon via tasks/questions/applied.jsonl so answered decisions are never forgotten. Source: tasks/specs/events-and-triggers.md §3

## Preconditions
- A question Q### has been answered by the owner.

## Scenario / Interaction Steps
1. Question Q### is answered, emitting question.answered and showing Q### as awaiting application.
2. Once the architect acts on the answer, the architect runs ai-orch questions apply Q### --by <actor> --ref <ref>.
3. The engine appends the record to tasks/questions/applied.jsonl and commits a question.applied event to the workspace event store.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Event task" --short "Event task" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch questions ask --tasks-dir "$T/tasks" --question "Use caching?" --context "Perf." --option "A=Yes: fast" --option "B=No: simple" --recommended A --blocks T001 --decider owner --asked-by "claude:orchestration" >/dev/null && ./bin/ai-orch questions answer Q001 --tasks-dir "$T/tasks" --choice A --text "Yes" --by owner >/dev/null && ./bin/ai-orch questions apply Q001 --tasks-dir "$T/tasks" --by claude --ref "T001" --note "Enabled cache" >/dev/null && ./bin/ai-orch events tail --workspace "$T" --json | jq -e "(.events | map(.type) | index(\"question.asked\") != null) and (.events | map(.type) | index(\"question.answered\") != null) and (.events | map(.type) | index(\"question.applied\") != null)" >/dev/null && test -f "$T/tasks/questions/applied.jsonl" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Every core mutation writes an outbox record (`prepared` -> `committed`) and assigns a monotonic workspace `seq` under the event lock.
- [ ] `ai-orch questions apply Q### --by <actor> --ref <ref>` appends an entry to `tasks/questions/applied.jsonl` without altering `## Answer` grammar.
- [ ] `ai-orch events tail --json` reads committed events across rotated chunks and supports `--since` and `--type` filtering.

## AI Validation Log

