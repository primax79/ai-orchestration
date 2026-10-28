# UC022 - Owner triages an inbox note with an agent run and reviews the proposal

- id: UC022
- title: Owner triages an inbox note with an agent run and reviews the proposal
- actor: Owner
- approval: proposed
- priority: P2
- linked-tasks: 09.4, 09.5, 09.10
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Agent triage inbox note

## Description & Business Value
Processes a raw inbox note and its attachments through a read-only agent triage run that emits a structured ai-orch-triage proposal for owner review and optional editing before creating tasks. Source: tasks/specs/inbox-notes.md §4

## Preconditions
- An inbox note N### exists in draft or ready status inside a git repository.

## Scenario / Interaction Steps
1. The owner selects Process with... on note N### (mode: triage).
2. The read-only agent run analyzes the note body and attachments without modifying tasks/ on disk and emits an ai-orch-triage block.
3. The owner reviews, optionally edits, and accepts the proposed tasks via ai-orch run accept-triage, which creates the accepted tasks and resolves N###.

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/repo" && git -C "$T/repo" init -q && git -C "$T/repo" config user.name "Test" && git -C "$T/repo" config user.email "test@example.com" && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch inbox add --tasks-dir "$T/repo/tasks" --title "Add export button" --kind feature --body "Export table as CSV." --status ready >/dev/null && git -C "$T/repo" add . && git -C "$T/repo" commit -q --no-verify -m "init" && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch config init-global >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch run preview --workspace "$T/repo" --note N001 --mode triage --tool kilo --json | jq -e ".ok == true and .mode == \"triage\"" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `triage` run mode executes in the workspace with a read-only permission policy and receives the note body plus attachments.
- [ ] The supervisor parses the final `ai-orch-triage` JSON block into a stored proposal without writing task files directly during the run.
- [ ] `ai-orch run accept-triage` (with optional `--only` and `--edits-file` overrides) creates the accepted tasks and resolves the note.

## AI Validation Log

