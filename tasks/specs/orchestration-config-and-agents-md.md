# Spec: Unified Orchestration Configuration (`orchestration.toml`) & `AGENTS.md` Renderer

> **Drives initiative:** [02](../done/02-task-and-config-spec/plan.md), [03](../done/03-skill-and-script-engine/plan.md)
> **Status:** Active implementation (Phase 1: Skill + Companion Python Scripts → CLI / VS Code Extension)

---

## 1. Goal & Core Architectural Principle

**Task definition and orchestration mechanics are strictly decoupled from execution channels.**

`ai-orchestration` is designed to work out of the box in **both** of these setups without changing a single rule of how tasks, acceptance criteria, or state transitions work:
1. **Single-Framework Native Setup (No MCP required):**
   - **Kilo-only:** Main Kilo session acts as Architect and dispatches parallel sub-sessions/worktrees via Kilo's native `agent_manager(mode="worktree")` and `task` subagents (selecting `deep-reasoning` vs. `bulk-execution` models within Kilo).
   - **Claude-only:** Main Claude Code session acts as Architect and dispatches parallel subagents/worktrees via Claude's native `Agent` tool (selecting `opus` / `sonnet` / `haiku`).
   - In single-framework mode, independent verification (`delivered → verified`) runs via a **fresh, context-blind subagent/session** (using the `deep-reasoning` profile) or a different model available inside the same framework.
2. **Multi-Framework / External MCP Setup:**
   - An Architect in one framework delegates execution or cross-verification to external frameworks via MCP servers (`kilo-mcp`, `claude-mcp`) or CLI (`codex`).

To support both seamlessly, `orchestration.toml` (Global + Project override), managed initially by a Skill + companion Python script (`orchestration_config.py`) and later by the standalone CLI / Web UI / VS Code Extension:
1. Declares which AI coding frameworks (`kilo`, `claude`, `codex`, ...) are enabled and both their **native in-session tools** (used when `executor == orchestrator`, requiring zero MCP) and their **external MCP/CLI bindings** (used when `executor != orchestrator`);
2. Configures the **per-tool model and reasoning effort/variant matrix** across the 4 cognitive profiles (`deep-reasoning`, `orchestration`, `bulk-execution`, `exploration`);
3. Configures default **routing** and **optional verification** (`self | cross-agent | blind-subagent | panel | owner`);
4. Captures **project-specific orchestration parameters** (shared DBs, ports, worker port range, conflict-prone files, zero-conflict registries, subsystem verification commands, local domain skills);
5. Deterministically renders or updates the project's `AGENTS.md` (adapting the Execution Mode table automatically to whether the project runs in Single-Framework Native mode or External MCP mode) inside managed markers (`<!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration -->`).

---

## 2. File Locations & Precedence (Never Versioned in Git)

**Core Rule:** Agent configuration (which tools `kilo`/`claude`/`codex` are enabled, which MCPs are registered, which models map to the 4 cognitive profiles, and who orchestrates vs. executes on this machine) is **local to the developer's environment and must never be committed to Git**.

1. **Global Machine Config**: `~/.config/ai-orchestration/orchestration.toml` (override via `$AI_ORCHESTRATION_CONFIG`).
   - Backward compatibility: if `~/.config/ai-architect-executor/roles.toml` exists and `orchestration.toml` does not, the loader can import its `[roles.<profile>]` entries.
2. **Per-Project Local Config (Unversioned)**: `<workspace>/.ai-orchestration.local.toml` (if already present locally, gitignored / in `.git/info/exclude`) or `~/.config/ai-orchestration/projects/<workspace-name>/orchestration.toml` (default write location outside the repo).
   - Unified lookup precedence order (`orchestration_config.find_project_config_path` / `inspect_project_config`, used across `orchestration_config`, `tasks_engine`, `orchestration_triggers`, and `orchestration_env`):
     1. `<workspace>/.ai-orchestration.local.toml` *(canonical, read-write)*
     2. `~/.config/ai-orchestration/projects/<workspace-name>/orchestration.toml` *(canonical, read-write, default when no file exists)*
     3. `<workspace>/orchestration.toml` *(legacy, read-only with warning)*
     4. `<workspace>/.ai-orchestration/orchestration.toml` *(legacy, read-only with warning)*
     5. `<workspace>/tasks/orchestration.toml` *(legacy, read-only with warning)*
     6. `<workspace>/.ai-orchestration.toml` *(legacy, read-only with warning)*
   - Deep-merged on top of the Global Config (`project` keys, `[routing]` overrides, `[verification]` overrides, `[tools.<id>.profiles.<profile>]` overrides).

---

## 3. Companion Script CLI Surface (`scripts/orchestration_config.py`)

All commands support `--json` (structured JSON on stdout, logs on stderr) so the exact same script serves the interactive skill today and the Web UI / VS Code extension tomorrow:

| Subcommand | Purpose |
| --- | --- |
| `show [--workspace <dir>] [--json]` | Load, merge, and display the effective (Global + Project) configuration and resolved role-to-model routing table. |
| `validate [--workspace <dir>] [--plugin-dir <dir>...] [--json]` | Run kit-internal checks (`skill-requirements.json`, no `model:` in `SKILL.md`) plus operator/project config validation (profiles, `xhigh` effort compatibility, verification rules, port ranges). |
| `set-profile <tool> <profile> --model <id> [--variant <v>] [--effort <e>] [--basis <b>] [--scope global\|project]` | Atomically set or update one `(tool, profile)` model assignment in `orchestration.toml`. |
| `init-global [--force]` | Create `~/.config/ai-orchestration/orchestration.toml` with the documented schema skeleton. |
| `init-project [--workspace <dir>] [--name <name>] [--orchestrator <tool>] [--executor <tool>]` | Create `~/.config/ai-orchestration/projects/<workspace-name>/orchestration.toml` (or `<workspace>/.ai-orchestration.local.toml` if already present). |
| `render-agents-md [--workspace <dir>] [--apply] [--check]` | Render the project-bound orchestration charter (Rules 1–4 + Verification Gate) from the merged config; with `--apply`, create or update the `<!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration -->` block in `<workspace>/AGENTS.md`. |
