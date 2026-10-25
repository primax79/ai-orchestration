# UC017 - Owner runs an independent cross-agent verification on a delivered task

- id: UC017
- title: Owner runs an independent cross-agent verification on a delivered task
- actor: Owner
- status: draft
- priority: P1
- linked-tasks: 07.4, 07.6, 07.7, 07.12
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Run cross-agent verification

## Description & Business Value
Enforces the verification independence guard when verifying a delivered task: refuses verification with the same tool that executed the task (unless downgraded via --allow-same-tool) and runs the cross-agent verifier in a detached throwaway worktree. Source: tasks/specs/agent-runs-from-ui.md §5.6

## Preconditions
- A task T### is in the delivered state with executor set to kilo.

## Scenario / Interaction Steps
1. Attempting to preview or start a verify run with tool kilo is refused by the independence guard.
2. Selecting an independent tool (e.g. claude) passes the guard and prepares a verify run in a detached throwaway worktree.
3. Upon completion, the parsed ai-orch-verdict block can be applied via apply-verdict to transition the task to verified or bounced.

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/repo" && git -C "$T/repo" init -q && git -C "$T/repo" config user.name "Test" && git -C "$T/repo" config user.email "test@example.com" && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/repo/tasks" --category engine --title "Verify test" --short "Verify test" --priority P1 --priority-reason "Core" --executor kilo --paths "tasks" --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && ./bin/ai-orch tasks transition T001 "in progress" --tasks-dir "$T/repo/tasks" >/dev/null && ./bin/ai-orch tasks transition T001 delivered --tasks-dir "$T/repo/tasks" >/dev/null && git -C "$T/repo" add . && git -C "$T/repo" commit -q --no-verify -m "init" && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch config init-global >/dev/null && (! PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch run preview --workspace "$T/repo" --task T001 --mode verify --tool kilo --target-run none >/dev/null 2>&1) && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch run preview --workspace "$T/repo" --task T001 --mode verify --tool claude --target-run none --json | jq -e ".ok == true and .mode == \"verify\" and .tool == \"claude\"" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `verify` mode is allowed only when the task is in `delivered` state.
- [ ] Verification is refused when `tool` matches the task `executor` or `target_run` tool unless `--allow-same-tool` is passed (which downgrades to `independent-session`).
- [ ] The verifier runs in a detached throwaway worktree checked out at `final_commit` (or workspace `HEAD` when `target_run: none`).
- [ ] `apply-verdict` parses the final `ai-orch-verdict` JSON block and refuses if the task bundle hash or target commit drifted.

## AI Validation Log

