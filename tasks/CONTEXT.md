# Project Context (Shared) — ai-orchestration

Durable, project-wide grounding shared by every initiative and task in `ai-orchestration`. Re-verify anything load-bearing against the real files before starting work.

## Codebase Map (Orchestration Ecosystem)

- **`./` (`ai-orchestration/`, this repo — formerly `ai-architect-executor`):**
  - `docs/`: architectural overview (`00-QUICKSTART-AND-PLAYBOOK.md`, `INSTALLATION.md`, `01`–`06`).
  - `tasks/`: live task registry (`00-INDEX.md`), formal specifications (`tasks/specs/`), initiatives (`01-repo-consolidation` .. `05-cli-and-ui-handoff`), and emergent tasks (`methodology/`, `server-and-bindings/`).
  - `plugins/architect-side/skills/`: `orchestration-workflow` (`SKILL.template.md` + `SKILL.md`), `task-pipeline` (`SKILL.md` + `references/template.md` + `scripts/tasks_engine.py`), `task-spec-authoring` (`SKILL.md`), `task-worktree-ops` (`SKILL.md` + `scripts/apply_fix_to_worktree.sh` + `references/worktree-git-plumbing.md`), `conflict-resolver` (`SKILL.template.md` + `SKILL.md`), `orchestration-metrics` (`SKILL.template.md` + `SKILL.md`).
  - `plugins/executor-side/skills/`: `executor-contract` (`SKILL.template.md` + `SKILL.md`).
  - `plugins/shared/skills/`: `orchestration-setup` (`SKILL.md` + `scripts/orchestration_config.py` + `scripts/validate_roles.py`).
  - `scripts/`: `generate_binding.py`, `regenerate_generic_skills.py`, `generate_skill_indices.py`, `orchestration_env.py`.
  - `bin/ai-orch` & `install.sh`: unified CLI entrypoint and from-scratch installer.
- **`../kilo-mcp/`:**
  - `server.py` & `test_server.py`: Python MCP server exposing 18 tools (including `kilo_implement`, `kilo_rag_search`, `kilo_task_progress`, `kilo_task_wait`, `kilo_task_result`, `kilo_task_cancel`, `kilo_log_issue`, `kilo_log_decision`, `kilo_metrics`).
  - `bindings/*.json`: binding maps for the 4 generated skills (`orchestration-workflow.json`, `executor-contract.json`, `conflict-resolver.json`, `orchestration-metrics.json`).
  - `plugins/architect-side/`: `kilo-mcp-orchestrator`, `kilo-mcp-metrics-analyst`, `kilo-mcp-conflict-resolver` skills + `agents/kilo-mcp-orchestrator-agent.md`.
  - `plugins/executor-side/`: `kilo-mcp-executor-contract`, `kilo-mcp-rag-explorer` skills.
  - `scripts/`: `regenerate_bound_skills.py`, `generate_skill_indices.py`.
- **`../claude-mcp/`:**
  - `SPEC.md`, `README.md`, `tasks/01-claude-mcp-server/plan.md`, and `reviews/001-spec-review-kilo-gemini-3.7-flash.md`: implementation-ready specification and 5-task plan for the headless Claude Code CLI MCP binding.
- **`../agentic-coding-kit/`:**
  - `plugins/third-party/skills/grill-me/`: pre-spec design-tree interview skill.

## Command / Verification Surface (Run from `ai-orchestration/`)

- **Regenerate generic skills & indices (`ai-orchestration`):**
  `python3 ./scripts/regenerate_generic_skills.py && python3 ./scripts/generate_skill_indices.py`
- **Validate role profiles & config (`ai-orchestration`):**
  `./bin/ai-orch config validate --plugin-dir ./plugins/architect-side --plugin-dir ./plugins/executor-side --plugin-dir ./plugins/shared`
- **Validate & sync `tasks/` tree (`ai-orchestration`):**
  `./bin/ai-orch tasks validate --tasks-dir ./tasks && ./bin/ai-orch tasks sync-index --tasks-dir ./tasks --check`
- **Run `ai-orchestration` unit test suites:**
  `../kilo-mcp/.venv/bin/pytest ./scripts/test_orchestration_env.py ./plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py ./plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py`
- **Regenerate & check bound skills (`kilo-mcp`):**
  `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py && python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check && python3 ../kilo-mcp/scripts/generate_skill_indices.py`
- **Run `kilo-mcp` test suite:**
  `../kilo-mcp/.venv/bin/pytest ../kilo-mcp/test_server.py`

## Cross-Cutting Locked-In Decisions

- **Strict Decoupling of Task/Orchestration Mechanics from Execution Channels:**
  - The task definition format (`tasks/`), acceptance/verification criteria, state machine (`open → in progress → delivered → verified → done`), and 6-phase Architect/Executor discipline are **100% autonomous from how tasks are executed**.
  - `ai-orchestration` works identically in **two execution topologies**:
    1. **Single-Framework Native Mode (Zero MCP required):** e.g., **Kilo-only**, **Claude-only**, or **Codex-only**, with independent verification performed by a fresh context-blind session (`independent-session`) or a different model within the same framework.
    2. **Cross-Framework / External MCP Mode:** e.g., Claude delegating to Kilo via `kilo-mcp`, Kilo delegating to Claude via `claude-mcp`, or multi-engine review panels (`kilo` + `claude` + `codex`).
- **Generate, don't duplicate (`ai-orchestration` → bindings):** Methodology edits go exclusively to `./plugins/*/skills/*/SKILL.template.md`; concrete tool names go into `../kilo-mcp/bindings/*.json` (and `../claude-mcp/bindings/*.json`). Never hand-edit generated `SKILL.md` files.
- **Protocol-agnostic upstream:** Nothing under `./plugins/` may name a concrete tool (`kilo_implement`, etc.) or a specific model (`opus`, `gemini-4-argon`).
- **Skills declare role profiles, never models:** Every skill declares one of `deep-reasoning`, `orchestration`, `bulk-execution`, `exploration` in `skill-requirements.json`, mapped per-machine in `~/.config/ai-orchestration/orchestration.toml`.
- **Emergent tasks convention (`task-pipeline` v0.2.1):** Work emerging mid-session is captured immediately to `tasks/<category>/T###-<slug>`; `delivered` ≠ `verified` ≠ `done`.
