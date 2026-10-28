# UC016 - Owner previews and launches an isolated execute run for a task

- id: UC016
- title: Owner previews and launches an isolated execute run for a task
- actor: Owner
- approval: proposed
- priority: P1
- linked-tasks: 07.1, 07.2, 07.3, 07.4, 07.7
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Launch execute run

## Description & Business Value
Allows the owner to select a tool, profile, and model for an emergent task, preview the exact prompt, redacted command line, planned worktree, and binding plan_hash, and launch an isolated background execution run. Source: tasks/specs/agent-runs-from-ui.md §3

## Preconditions
- An emergent task T### exists in open or bounced state inside a clean git repository.

## Scenario / Interaction Steps
1. The owner requests run options and run preview for T### in execute mode.
2. The engine validates all guards, resolves the tool/profile/model matrix, and returns the prompt, argv_display, planned worktree/branch, and binding plan_hash.
3. When started, the supervisor spawns the headless agent in its own process group and worktree and transitions the task to in progress.

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/repo" && git -C "$T/repo" init -q && git -C "$T/repo" config user.name "Test" && git -C "$T/repo" config user.email "test@example.com" && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/repo/tasks" --apply --expect-plan-hash "$H" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/repo/tasks" --category engine --title "Run preview test" --short "Run preview" --priority P1 --priority-reason "Core" --executor kilo --paths "tasks" --goal "Goal" --step "Step 1" --verification "pytest" >/dev/null && git -C "$T/repo" add . && git -C "$T/repo" commit -q --no-verify -m "init" && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch config init-global >/dev/null && PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg.toml" ./bin/ai-orch run preview --workspace "$T/repo" --task T001 --mode execute --tool kilo --json | jq -e ".ok == true and (.plan_hash | length > 10) and .mode == \"execute\"" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch run preview` returns a binding `plan_hash`, `prompt_sha256`, `argv_display` (with secret references redacted), and planned worktree/branch without modifying disk.
- [ ] Prompt is passed via stdin or file (never on process `argv`).
- [ ] Launching an `execute` run creates an isolated git worktree under `../.worktrees/<repo>/<run_id>` on branch `run/<run_id>` and transitions the task to `in progress`.
- [ ] `mark-delivered` verifies the run succeeded, the worktree is clean on `run/<run_id>`, at least one commit was added beyond `base_commit`, and a `## Final Report` was parsed.

## AI Validation Log

