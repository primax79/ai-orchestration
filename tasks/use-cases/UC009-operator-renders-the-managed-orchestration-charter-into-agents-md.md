# UC009 - Operator renders the managed orchestration charter into AGENTS.md

- id: UC009
- title: Operator renders the managed orchestration charter into AGENTS.md
- actor: Operator (CLI)
- approval: proposed
- priority: P1
- linked-tasks: 03.1, T011
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Render AGENTS.md block

## Description & Business Value
Deterministically renders or updates the project-bound orchestration charter inside managed HTML comment markers in AGENTS.md while preserving all project-authored documentation outside the markers. Source: tasks/specs/orchestration-config-and-agents-md.md §3

## Preconditions
- Workspace contains an AGENTS.md file and an active orchestration configuration.

## Scenario / Interaction Steps
1. The operator runs ai-orch config render-agents-md --workspace <dir> --apply.
2. The tool writes or updates the <!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration --> block in AGENTS.md while keeping surrounding content intact.
3. Running ai-orch config render-agents-md --check exits 0 when AGENTS.md matches the active configuration.

## Automated Verification Command
```bash
T=$(mktemp -d) && printf "# My Project\n\nCustom intro.\n" > "$T/AGENTS.md" && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/orchestration.toml" ./bin/ai-orch config init-global >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/orchestration.toml" ./bin/ai-orch config render-agents-md --workspace "$T" --allow-global-routing --allow-unknown-models --apply >/dev/null && grep -q "Custom intro." "$T/AGENTS.md" && grep -q "BEGIN ai-orchestration" "$T/AGENTS.md" && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/orchestration.toml" ./bin/ai-orch config render-agents-md --workspace "$T" --allow-global-routing --allow-unknown-models --check >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch config render-agents-md --apply` inserts or replaces only the `<!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration -->` section in `<workspace>/AGENTS.md`.
- [ ] Project-authored content outside the markers is preserved verbatim.
- [ ] `ai-orch config render-agents-md --check` exits 0 when synchronized and non-zero if `AGENTS.md` has drifted from the active configuration.

## AI Validation Log

