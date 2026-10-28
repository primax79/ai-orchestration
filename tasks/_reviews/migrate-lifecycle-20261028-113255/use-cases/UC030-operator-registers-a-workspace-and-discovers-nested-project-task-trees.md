# UC030 - Operator registers a workspace and discovers nested project task trees

- id: UC030
- title: Operator registers a workspace and discovers nested project task trees
- actor: Operator (CLI)
- status: draft
- priority: P1
- linked-tasks: 16.3, T039, T049
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Register workspace projects

## Description & Business Value
Registers a root workspace folder with an immutable UUID and human slug in the SQLite broker registry and discovers child project task trees (skipping hidden, gitignored, build, worktree, and inner workspace folders) via preview-then-apply. Source: tasks/specs/orchestration-broker-mcp.md §1

## Preconditions
- A workspace directory contains a top-level tasks/ tree and one or more child repositories with tasks/00-INDEX.md.

## Scenario / Interaction Steps
1. The operator previews and applies ai-orch workspace register <path> --id <slug>.
2. The operator runs ai-orch projects discover <workspace> to propose child projects and applies the proposal with --expect-hash.
3. Running ai-orch workspace show <slug> returns _workspace and the registered child projects.

## Automated Verification Command
```bash
T=$(mktemp -d) && mkdir -p "$T/ws/proj-a" && H1=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/tasks" --apply --expect-plan-hash "$H1" >/dev/null && H2=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/ws/proj-a/tasks" --apply --expect-plan-hash "$H2" >/dev/null && WH=$(PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch workspace register "$T/ws" --id demo-ws --config-dir "$T/cfg" --json | jq -r .plan_hash) && PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch workspace register "$T/ws" --id demo-ws --config-dir "$T/cfg" --apply --expect-hash "$WH" >/dev/null && DH=$(PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch projects discover "$T/ws" --config-dir "$T/cfg" --json | jq -r .plan_hash) && PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch projects discover "$T/ws" --config-dir "$T/cfg" --apply --expect-hash "$DH" >/dev/null && PATH="/opt/homebrew/bin:$PATH" ./bin/ai-orch workspace show demo-ws --config-dir "$T/cfg" --json | jq -e "(.workspace.projects | map(.slug) | index(\"proj-a\") != null)" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch workspace register` previews by default with a `plan_hash` and writes `[workspace]` (`uuid`, `id`, `title`) plus SQLite registry entries only when `--apply --expect-hash` is given.
- [ ] `ai-orch projects discover` scans for child `tasks/00-INDEX.md` trees while excluding hidden folders, git-ignored paths, build/venv dirs, worktrees, and inner registered workspaces.
- [ ] Nested registered workspaces follow the nearest-workspace ownership rule and appear as read-only `sub_workspaces` in the outer workspace.

## AI Validation Log

