# UC011 - Operator installs orchestration skills into an assistant environment

- id: UC011
- title: Operator installs orchestration skills into an assistant environment
- actor: Operator (CLI)
- status: draft
- priority: P2
- linked-tasks: 05.2, 05.4, T056
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Install assistant skills

## Description & Business Value
Installs or updates the curated orchestration skills across Claude Code, Kilo Code, or Codex in global or project scope using a hash-verified execution plan. Source: tasks/specs/orchestration-extension-spec.md §2

## Preconditions
- Source repository ai-orchestration is available locally.

## Scenario / Interaction Steps
1. The operator previews the skill installation plan via ai-orch env install-skills --dry-run --json to obtain the plan_hash.
2. The operator applies the installation passing --expect-plan-hash.
3. The selected plugin skills are installed into the target assistant directory with provenance tracking.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch env --home "$T" install-skills --assistants claude --scope global --repo ai-orchestration --plugins architect-side --dry-run --json | jq -r .plan_hash) && ./bin/ai-orch env --home "$T" install-skills --assistants claude --scope global --repo ai-orchestration --plugins architect-side --expect-plan-hash "$H" --json | jq -e ".ok == true" && test -f "$T/.claude/skills/task-pipeline/SKILL.md" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch env install-skills --dry-run --json` computes the execution plan and returns a deterministic `plan_hash`.
- [ ] Applying the install with `--expect-plan-hash` copies or symlinks the requested plugin skills into the target assistant directory (`~/.claude/skills`, `~/.kilo/skills`, or `~/.codex/skills`).
- [ ] Duplicate generic and MCP-bound skill trigger conflicts are prevented or flagged by policy.

## AI Validation Log

