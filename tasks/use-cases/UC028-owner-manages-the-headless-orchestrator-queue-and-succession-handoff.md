# UC028 - Owner manages the headless orchestrator queue and succession handoff

- id: UC028
- title: Owner manages the headless orchestrator queue and succession handoff
- actor: Owner
- status: draft
- priority: P2
- linked-tasks: 12.5, 12.8, 12.9, 12.10, T026, T027
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Manage headless orchestrator

## Description & Business Value
Maintains a persistent headless orchestrator role per workspace with a serialized turn queue (prioritizing owner chat messages while preventing starvation of event batches) and fenced generation rotation with file-derived handoff prompts. Source: tasks/specs/events-and-triggers.md §0

## Preconditions
- Workspace has a valid orchestration configuration.

## Scenario / Interaction Steps
1. The owner starts the headless orchestrator role via ai-orch orchestrator start --tool <tool>.
2. Owner chat messages and coalesced event batches are enqueued into .ai-orchestration/orchestrator/queue/.
3. When context bounds are reached or the owner reassigns/rotates the role, a fenced handoff prompt is built from on-disk state for generation N+1.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch config init-global >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch orchestrator start --workspace "$T" --tool claude --json | jq -e ".status == \"active\" and .generation == 1" >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch orchestrator enqueue --workspace "$T" --type owner_chat --priority owner --message "Check open tasks" --json | jq -e ".status == \"enqueued\"" >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch orchestrator hand-off --workspace "$T" --json | jq -e "(.handoff_prompt | length > 20)" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch orchestrator start` initializes `.ai-orchestration/orchestrator.json` with generation 1 and registers the headless orchestrator session.
- [ ] `ai-orch orchestrator enqueue` atomically writes turn requests into `.ai-orchestration/orchestrator/queue/` and enforces owner priority with anti-starvation (at least 1 event batch after every 3 owner turns).
- [ ] `ai-orch orchestrator rotate` / `hand-off` builds a file-derived handoff prompt (`00-INDEX.md`, open/unapplied questions, active runs, recent events, pending queue) for fenced succession.

## AI Validation Log

