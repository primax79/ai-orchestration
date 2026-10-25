# UC002 - Operator validates a single use case probe and records the verdict

- id: UC002
- title: Operator validates a single use case probe and records the verdict
- actor: Operator (CLI)
- status: draft
- priority: P1
- linked-tasks: 15.3
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Validate use case probe

## Description & Business Value
Executes a use case automated verification command, captures stdout/stderr and exit code, updates last-tested and last-verdict headers, transitions status to verified or failing, and appends an entry to the AI Validation Log. Source: tasks/specs/use-case-management-and-ai-validation.md §3

## Preconditions
- At least one use case file UC### exists in tasks/use-cases/ with a runnable verification command.

## Scenario / Interaction Steps
1. The operator runs ai-orch tasks use-cases validate UC###.
2. The engine executes the verification command in a subprocess with a timeout.
3. On exit code 0, status becomes verified, last-verdict becomes pass, and the execution evidence is appended to ## AI Validation Log.

## Automated Verification Command
```bash
T=$(mktemp -d) && ~/.local/bin/ai-orch tasks use-cases create --tasks-dir "$T/tasks" --title "Probe UC" --short "Probe UC" --actor "Operator (CLI)" --status active --priority P1 --verification-type automated-probe --verification-command "echo ok" && ~/.local/bin/ai-orch tasks use-cases validate UC001 --tasks-dir "$T/tasks" --json | jq -e ".verdict == \"pass\" and .status == \"verified\"" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Running `ai-orch tasks use-cases validate UC###` executes the fenced bash verification command with a configurable timeout.
- [ ] Exit code 0 updates `last-verdict: pass`, `status: verified`, and `last-tested: <YYYY-MM-DD>`.
- [ ] Non-zero exit code updates `last-verdict: fail`, `status: failing`, and appends captured stdout/stderr evidence to `## AI Validation Log`.

## AI Validation Log

