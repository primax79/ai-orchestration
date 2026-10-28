# UC003 - Operator runs a product validation campaign with regression detection

- id: UC003
- title: Operator runs a product validation campaign with regression detection
- actor: Operator (CLI)
- approval: proposed
- priority: P2
- linked-tasks: 15.4, T055
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Run validation campaign

## Description & Business Value
Evaluates all active use cases across the product, computes the functional readiness score, flags regressions where a previously passing use case now fails, and writes a timestamped report under tasks/_reviews/. Source: tasks/specs/use-case-management-and-ai-validation.md §5

## Preconditions
- Multiple use cases exist in tasks/use-cases/, including previously passing ones.

## Scenario / Interaction Steps
1. The operator runs ai-orch tasks use-cases campaign --tasks-dir tasks.
2. The engine runs each use case probe and compares the new verdict with last-verdict.
3. Any use case flipping from pass to fail is flagged as a regression.
4. The engine writes tasks/_reviews/validation-campaign-<ts>.md with the readiness score and compliance matrix.

## Automated Verification Command
```bash
T=$(mktemp -d) && ./bin/ai-orch tasks use-cases create --tasks-dir "$T/tasks" --title "Regress UC" --short "Regress UC" --actor "Operator (CLI)" --status verified --priority P1 --verification-type automated-probe --verification-command "exit 1" && ./bin/ai-orch tasks use-cases record-validation UC001 --tasks-dir "$T/tasks" --verdict pass --summary "Initial pass" && ./bin/ai-orch tasks use-cases validate UC001 --tasks-dir "$T/tasks" >/dev/null 2>&1 || true && ./bin/ai-orch tasks use-cases record-validation UC001 --tasks-dir "$T/tasks" --verdict pass --summary "Reset pass" && ./bin/ai-orch tasks use-cases campaign --tasks-dir "$T/tasks" --json | jq -e ".regressions_count == 1 and (.report_file | contains(\"_reviews/validation-campaign-\"))" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Campaign runner evaluates all active use cases (or filtered by `--actor`) and computes `readiness_score` as percentage verified.
- [ ] Any use case whose `last-verdict` was `pass` and now evaluates to `fail` is reported in the `regressions` list.
- [ ] Campaign report is written to `tasks/_reviews/validation-campaign-<timestamp>.md` without creating a phantom task category.

## AI Validation Log

