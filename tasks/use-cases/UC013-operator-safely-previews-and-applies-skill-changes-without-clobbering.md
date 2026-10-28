# UC013 - Operator safely previews and applies skill changes without clobbering

- id: UC013
- title: Operator safely previews and applies skill changes without clobbering
- actor: Operator (CLI)
- approval: proposed
- priority: P1
- linked-tasks: 06.2, 06.3, 06.4
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Safe skill install plan

## Description & Business Value
Prevents accidental overwrite of foreign or locally modified skills during installation by defaulting to skip, requiring explicit --overwrite and a matching --expect-plan-hash, and archiving replaced directories into .ai-orch-trash/. Source: tasks/specs/control-plane-safety.md §2.1

## Preconditions
- An assistant skill directory contains an unmanaged or locally modified skill.

## Scenario / Interaction Steps
1. The operator runs ai-orch env install-skills --dry-run; the foreign skill is marked as skip in the plan.
2. The operator explicitly passes --overwrite <skill> --dry-run to obtain a content-hashed replacement plan.
3. The operator applies the plan with --expect-plan-hash; the old directory is moved to .ai-orch-trash/<ts>/<name> and the new skill is installed with a provenance receipt.

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/.claude/skills/task-pipeline" && echo "custom foreign skill" > "$T/.claude/skills/task-pipeline/SKILL.md" && ./bin/ai-orch env --home "$T" install-skills --assistants claude --scope global --repo ai-orchestration --plugins architect-side --dry-run --json | jq -e ".plan[] | select(.current_state == \"foreign\" and .action == \"skip\")" >/dev/null && H=$(./bin/ai-orch env --home "$T" install-skills --assistants claude --scope global --repo ai-orchestration --plugins architect-side --overwrite task-pipeline --dry-run --json | jq -r .plan_hash) && ./bin/ai-orch env --home "$T" install-skills --assistants claude --scope global --repo ai-orchestration --plugins architect-side --overwrite task-pipeline --expect-plan-hash "$H" --json | jq -e ".ok == true" >/dev/null && test -d "$T/.config/ai-orchestration/trash" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Every plan entry carries `before_sha256` and `after_sha256`, and `plan_hash` is computed over the full plan content.
- [ ] Targets classified as `foreign` or `modified-or-outdated` are skipped unless explicitly named in `--overwrite`.
- [ ] Replaced or deleted skill directories are moved to `<skills_dir>/.ai-orch-trash/<timestamp>/<name>` instead of being permanently deleted.
- [ ] Installed skills carry a `.ai-orch-source.json` provenance receipt.

## AI Validation Log

