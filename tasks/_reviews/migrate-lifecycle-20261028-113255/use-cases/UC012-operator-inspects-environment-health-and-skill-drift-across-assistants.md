# UC012 - Operator inspects environment health and skill drift across assistants

- id: UC012
- title: Operator inspects environment health and skill drift across assistants
- actor: Operator (CLI)
- status: draft
- priority: P2
- linked-tasks: 05.2, 05.4, 13.1, T056
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Inspect environment health

## Description & Business Value
Runs the Environment Health Doctor to inspect CLI binary availability, per-assistant skill drift (up-to-date, modified-locally, missing, conflict), and MCP server readiness across Kilo, Claude, and Codex. Source: tasks/specs/orchestration-extension-spec.md §2

## Preconditions
- Operator invokes ai-orch env status on a machine or workspace.

## Scenario / Interaction Steps
1. The operator runs ai-orch env status --workspace <dir> --json.
2. The engine probes CLI binaries, installed skills, MCP configurations, and stray files.
3. The structured report returns grouped findings, severity counts, and per-environment skill states.

## Automated Verification Command
```bash
T=$(mktemp -d) && ./bin/ai-orch env --home "$T" status --workspace "$T" --json | jq -e ".clis != null and .environments != null and .finding_groups != null" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch env status --json` reports CLI binary readiness (`kilo`, `claude`, `codex`) and authentication state.
- [ ] Per-environment skill entries classify drift by content comparison (`up-to-date`, `modified-locally`, `missing`, `conflict`).
- [ ] Findings are grouped with severity counts and actionable remediation commands.

## AI Validation Log

