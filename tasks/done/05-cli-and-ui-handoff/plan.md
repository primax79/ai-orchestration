# 05 - Standalone CLI (`ai-orch`), From-Scratch Installer & Extension Control Plane

- **Short:** CLI installer control plane

> **Derived from:** [`../specs/orchestration-extension-spec.md`](../../specs/orchestration-extension-spec.md) and [`../../docs/03-task-model-and-ui-architecture.md`](../../../docs/03-task-model-and-ui-architecture.md)

## Tasks (One Task = One Commit)

### 05.1 - Unified `bin/ai-orch` CLI Entrypoint (`config`, `tasks`, `render-agents-md`, `describe`)
- **Status:** `done` (2026-10-15) · **Short:** Unified ai-orch CLI
- **Goal:** Provide a single `bin/ai-orch` CLI wrapper over `orchestration_config.py` and `tasks_engine.py` with `--json` output and `describe`.

### 05.2 - From-Scratch Installer & Environment Doctor (`scripts/orchestration_env.py`, `install.sh`, `ai-orch env`)
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15) · **Short:** Installer and Doctor
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`, `install.sh`, `bin/ai-orch`
- **Goal:** Provide a zero-dependency script (`scripts/orchestration_env.py`, exposed as `./bin/ai-orch env <status|install|register-mcp>` and `./install.sh`) for users installing from scratch and for Macro-Tasks 2 & 3 of the Extension:
  1. **Download / Clone / Update** `ai-orchestration` and `kilo-mcp` (from GitHub into `~/.ai-orchestration/repos/` or using local checkouts when present);
  2. **Install Skills & Agents** into Kilo Code (`~/.kilo/skills` or `<workspace>/.kilo/skills`) and Claude Code (`~/.claude/skills` or `<workspace>/.claude/skills`), supporting both Single-Framework generic skills (`architect-side`, `executor-side`, `shared`) and MCP-bound skills (`kilo-mcp`), and detecting duplicate generic+bound conflicts;
  3. **Provision & Register MCP Servers** (`kilo-mcp`, `claude-mcp`): create/update Python `.venv`, install package, and register the MCP server in Claude (`~/.claude.json` / `.mcp.json`) and Kilo (`~/.config/kilo/kilo.json` / `.kilo/kilo.jsonc`);
  4. **Verify Environment Status (`status` / `doctor`)**: report JSON/human status of CLI binaries (`kilo`, `claude`, `codex`), installed skills (with content-hash drift detection: `up-to-date`, `modified-locally`, `missing`, `conflict`), registered MCP servers, and `orchestration.toml`.
- **Verification:** `pytest scripts/test_orchestration_env.py` (3 passed) and `./bin/ai-orch env status --json` pass.

### 05.3 - Extension / Web UI Backend & Backlog Manager View (Macro-Task 1)
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** Backlog Manager backend
- **Repo:** `ai-orchestration-ui/`
- **Goal:** Build the Backlog Manager UI (Progress overview, `Next up` queue, Kanban board by state, Initiative/Category tree, and Task/Spec detail editor for priority, assignee/executor, profile, verification-mode, and state transitions) backed by `ai-orch tasks --json`.
- **Verification:** Unit tests in `backend/test_server.py` pass and Vite compiles `frontend/dist/` cleanly.

### 05.4 - Extension / Web UI Environment Installer, Doctor & Orchestrator Configurator (Macro-Tasks 2, 3, 4)
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** Installer and configurator UI
- **Repo:** `ai-orchestration-ui/`
- **Goal:** Build the UI views for:
  - **Macro-Task 2 & 3 (Skills & MCP Installer + Environment Doctor):** backed by `ai-orch env status --json` and `ai-orch env install --json`;
  - **Macro-Task 4 (Project Orchestrator Configurator):** visual editor for Global & Project `orchestration.toml` (active frameworks, primary orchestrator, per-tool model matrix, verification policy, isolation rules) + one-click `AGENTS.md` preview and apply (`ai-orch render-agents-md --apply`).
- **Verification:** Starlette backend serves static bundle at `/`, all REST and WebSocket routes tested, ready for embedding into VS Code Webview panel via `vscode.postMessage` in `frontend/src/api.ts`.
