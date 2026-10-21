# Architect-Side Plugin (`plugins/architect-side`)

Architect-side skills for the protocol-agnostic Architect/Executor orchestration pattern across Single-Framework Native (Kilo-only, Claude-only, Codex-only) and Multi-Framework MCP (`kilo-mcp`, `claude-mcp`, `codex`) modes.

## Included Skills

- **`orchestration-workflow`** (`orchestration` profile) — 6-phase Architect/Executor loop (Discovery → Isolation → Dispatch → Monitor → Verify → Merge).
- **`task-pipeline`** (`orchestration` profile) — Manages the `tasks/` pipeline (`00-INDEX.md`, `specs/`, initiatives `NN-<slug>`, emergent tasks `T###`) and task state transitions.
- **`task-spec-authoring`** (`deep-reasoning` profile) — Writing grounded task specifications, acceptance criteria, verification gates, and review panels.
- **`task-worktree-ops`** (`deep-reasoning` profile) — Git worktree isolation and safety mechanics.
- **`conflict-resolver`** (`deep-reasoning` profile) — Resolving merge conflicts across parallel execution branches.
- **`orchestration-metrics`** (`deep-reasoning` profile) — Analyzing delegation ROI, cost efficiency, and spec guardrails.

## Standalone Project Versioning of `task-pipeline`

`task-pipeline` (`plugins/architect-side/skills/task-pipeline/`) is designed to be fully self-contained:

- **Direct In-Repo Versioning:** The `task-pipeline` skill folder can be copied and versioned directly inside any target project repository (for example at `.kilo/skills/task-pipeline/` or `.claude/skills/task-pipeline/`).
- **100% Standalone Stdlib Execution:** It works out of the box using only Python 3 standard library modules:
  ```bash
  python3 <skill-dir>/scripts/tasks_engine.py validate --tasks-dir tasks
  python3 <skill-dir>/scripts/tasks_engine.py sync-index --apply --tasks-dir tasks
  python3 <skill-dir>/scripts/tasks_engine.py upgrade --tasks-dir tasks
  ```
- **Zero External Dependencies:** No VS Code extension, no broker MCP server, and no `ai-orchestration` repository checkout is required. Event emission silently and gracefully disables itself when `orchestration_events` is unavailable without spamming `stderr`.
- **Pure Markdown Fallback:** Developers and AI agents without Python or CLI access can manage tasks directly using plain Markdown editing (`tasks/AGENTS.md` + `references/template.md`).

## Global CLI Access via `ai-orch`

For global command-line access without running a broker MCP daemon:
- Run `ai-orch install-launcher --apply` to install `~/.local/bin/ai-orch` as the stable, version-free entry point.
- This provides direct CLI commands (`ai-orch tasks ...`, `ai-orch env status`, etc.) across all projects on your machine.
