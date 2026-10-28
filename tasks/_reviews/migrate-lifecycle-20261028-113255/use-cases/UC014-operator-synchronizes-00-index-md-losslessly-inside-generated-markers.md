# UC014 - Operator synchronizes 00-INDEX.md losslessly inside generated markers

- id: UC014
- title: Operator synchronizes 00-INDEX.md losslessly inside generated markers
- actor: Operator (CLI)
- status: draft
- priority: P1
- linked-tasks: 06.1, T050
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Lossless index sync

## Description & Business Value
Updates only the generated table regions inside <!-- ai-orch:generated ... --> markers in tasks/00-INDEX.md while preserving hand-written prose, custom Result cells, and historical Closed dates. Source: tasks/specs/control-plane-safety.md §2.2

## Preconditions
- tasks/00-INDEX.md has been adopted with generated-region markers.

## Scenario / Interaction Steps
1. The operator or architect adds custom prose outside the generated markers in tasks/00-INDEX.md and creates or updates tasks.
2. The operator runs ai-orch tasks sync-index --tasks-dir tasks --apply.
3. The generated tables reflect the new task rows while all prose outside the markers and existing Done metadata remain untouched.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && printf "\nCustom prose outside markers.\n" >> "$T/tasks/00-INDEX.md" && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Index test" --short "Index test" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks sync-index --tasks-dir "$T/tasks" --apply >/dev/null && grep -q "Custom prose outside markers." "$T/tasks/00-INDEX.md" && grep -q "T001" "$T/tasks/00-INDEX.md" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `sync-index --apply` modifies only the content inside `<!-- ai-orch:generated <section> -->` markers and refuses on unmarked indices unless `--adopt` is used.
- [ ] Existing `Done` table rows preserve their `Closed` date and custom `Result` cells.
- [ ] Prose and sections outside the generated markers are preserved verbatim.
- [ ] Writes are atomic and honor `--expect-hash` when supplied.

## AI Validation Log

