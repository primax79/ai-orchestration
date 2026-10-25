# UC029 - Operator evaluates event triggers and confirms proposed actions

- id: UC029
- title: Operator evaluates event triggers and confirms proposed actions
- actor: Operator (CLI)
- status: draft
- priority: P2
- linked-tasks: 12.4, 12.6, 12.16, T024, T028
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Evaluate event triggers

## Description & Business Value
Evaluates configured trigger rules against new workspace events under rate limits and loop guards, running unattended event turns with a reduced-capability policy and recording proposed actions for 1-click owner confirmation or rejection. Source: tasks/specs/events-and-triggers.md §5

## Preconditions
- Workspace event store contains committed events and orchestration.toml defines trigger rules.

## Scenario / Interaction Steps
1. The operator or daemon runs ai-orch triggers run-once / status.
2. Matching rules evaluate events since the scan watermark while enforcing rate limits, kill switch, and loop depth guards.
3. Mutating actions proposed by unattended turns are stored as proposals until confirmed with --expect-hash or rejected with a reason.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch config init-global >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Trigger test" --short "Trigger test" --priority P1 --priority-reason "Core" --executor kilo --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/tasks" >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch triggers status --workspace "$T" --json | jq -e ".ok == true" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Trigger rules that launch agents default to `enabled = false` and honor the global `[triggers] enabled` kill switch.
- [ ] Rate limits (`max_per_hour`, persisted token buckets) and loop depth guards (maximum depth 3 via `cause` tracking) are enforced.
- [ ] Unattended event turns run under the reduced-capability policy (wrapping untrusted file/event data with provenance delimiters) and emit proposed actions requiring explicit `--expect-hash` confirmation.

## AI Validation Log

