# UC008 - Operator configures role-to-model profiles and routing in TOML

- id: UC008
- title: Operator configures role-to-model profiles and routing in TOML
- actor: Operator (CLI)
- status: draft
- priority: P1
- linked-tasks: 02.1, 03.1, T033
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Configure role profiles

## Description & Business Value
Allows an operator to initialize and update global or per-project orchestration.toml role profiles (deep-reasoning, orchestration, bulk-execution, exploration) and inspect the merged configuration without committing machine-specific settings to Git. Source: tasks/specs/orchestration-config-and-agents-md.md §2

## Preconditions
- Python 3.11+ with stdlib tomllib is available.

## Scenario / Interaction Steps
1. The operator runs ai-orch config init-global to scaffold orchestration.toml.
2. The operator runs ai-orch config set-profile <tool> <profile> --model <id> --variant <v> to bind a cognitive profile.
3. Running ai-orch config show --json merges global and project overrides and outputs the active role matrix.

## Automated Verification Command
```bash
T=$(mktemp -d) && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/orchestration.toml" ./bin/ai-orch config init-global >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/orchestration.toml" ./bin/ai-orch config set-profile kilo bulk-execution --model "google/gemini-3.8-flash" --variant medium --scope global >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/orchestration.toml" ./bin/ai-orch config show --workspace "$T" --json | jq -e ".config.tools.kilo.profiles.\"bulk-execution\".model == \"google/gemini-3.8-flash\"" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch config init-global` creates the global `orchestration.toml` skeleton (respecting `$AI_ORCHESTRATION_CONFIG` isolation).
- [ ] `ai-orch config set-profile <tool> <profile> --model <id>` atomically updates the model and variant/effort for one `(tool, profile)` pair.
- [ ] `ai-orch config show --json` deep-merges project overrides over global config and outputs the effective role matrix.

## AI Validation Log

