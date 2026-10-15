# Orchestration Configuration Schema (`orchestration.toml`)

> **Goal:** A unified, hierarchical, **unversioned (local-environment only)** configuration file (Global `~/.config/ai-orchestration/orchestration.toml` + optional per-project local override `~/.config/ai-orchestration/projects/<repo>/orchestration.toml` or gitignored `.ai-orchestration.local.toml`) that strictly separates **versioned task/spec definitions in Git (`tasks/`)** from **local agent & model execution settings**, supporting both:
> - **Single-Framework Native setups** (e.g. Kilo-only or Claude-only, dispatching parallel native worktrees/sub-sessions and running independent blind-session verification with zero MCP servers); and
> - **Multi-Framework MCP setups** (delegating execution or cross-agent verification to external frameworks via `kilo-mcp`, `claude-mcp`, or CLI).
>
> Specifically, `orchestration.toml` defines:
> 1. Which tools/frameworks exist (`kilo`, `claude`, `codex`, ...) and how to invoke them both **natively** (within the same framework) and **externally** (via MCP server or CLI);
> 2. Which model + reasoning effort/variant each tool uses for each cognitive profile (`deep-reasoning`, `orchestration`, `bulk-execution`, `exploration`);
> 3. Which tool/mode handles which activity (primary executor, independent in-framework verifier `independent-session`, cross-framework verifier `cross-agent`, or `panel`);
> 4. Project-specific isolation & verification rules (shared DBs, ports, conflict-prone files, verification commands) used both by the Python Orchestration Server/UI and to auto-generate the project's `AGENTS.md` (like `~/works/ricerca_auto/AGENTS.md`).

---

## 1. Two-Level Hierarchy: Global Base + Project Override

1. **Global Config (`~/.config/ai-orchestration/orchestration.toml`)** *(evolves and replaces `~/.config/ai-architect-executor/roles.toml`)*:
   - Defines your available **Tools / Executors** (`kilo`, `claude`, `codex`), their **MCP bindings** (`kilo-mcp`, `claude-mcp`), and the **per-tool model matrix** (which model + variant/effort each tool uses for `deep-reasoning`, `orchestration`, `bulk-execution`, `exploration`).
   - Defines your default **Workflow Routing & Verification Policy** (e.g., default executor for `bulk-execution`, default cross-agent verifier when `verification-mode = "cross-agent"` or `"panel"`).

2. **Project Config (`<repo>/.ai-orchestration.toml` or `<repo>/tasks/orchestration.toml`)**:
   - Optional; inherits everything from Global and overrides only what differs for this project:
     - Which tools/MCPs are active in this project;
     - Optional model overrides per activity;
     - **Project Isolation & Verification metadata** (shared ports, DB files, conflict-prone files, zero-conflict registries, verification commands per subsystem, project-local domain skills).
   - **Drives two things automatically**:
     1. **Renders/updates the project's `AGENTS.md`** (`<!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration -->`) so any session opened in that repo has the exact tables of `ricerca_auto/AGENTS.md` always in sync;
     2. **Configures the Python Orchestration Server & Web UI** so when you click *"Run Task"* or *"Cross-Verify with Another Agent"*, the server knows exactly which MCP/CLI tool, model, variant, worktree flag, and verification commands to use.

---

## 2. Concrete Schema Design (`orchestration.toml`)

### 2.1 Global Configuration (`~/.config/ai-orchestration/orchestration.toml`)

```toml
schema_version = 1
last_verified = "2026-10-15"

# ─────────────────────────────────────────────────────────────────────────────
# 1. TOOLS & DISPATCH CHANNELS (How each assistant is invoked)
# ─────────────────────────────────────────────────────────────────────────────

[tools.kilo]
enabled = true
# When the orchestrator IS Kilo, it uses native tools (`agent_manager`, `task`).
# When dispatched from outside (Claude, Python Server, Web UI), it uses MCP (`kilo-mcp`) or CLI.
native_worktree_tool = "agent_manager(mode='worktree')"
native_subagent_tool = "task"
mcp_server = "kilo-mcp"
mcp_implement_tool = "kilo_implement"
mcp_progress_tool = "kilo_task_progress"
mcp_wait_tool = "kilo_task_wait"
mcp_result_tool = "kilo_task_result"
mcp_cancel_tool = "kilo_task_cancel"
mcp_rag_tool = "kilo_rag_search"
cli_command = "kilo"

[tools.claude]
enabled = true
native_worktree_tool = "Agent(isolation='worktree')"
native_subagent_tool = "Agent"
mcp_server = "claude-mcp"
mcp_implement_tool = "claude_implement"
mcp_progress_tool = "claude_task_progress"
mcp_result_tool = "claude_task_result"
mcp_cancel_tool = "claude_task_cancel"
cli_command = "claude"

[tools.codex]
enabled = true
mcp_server = ""          # CLI-driven
cli_command = "codex"

# ─────────────────────────────────────────────────────────────────────────────
# 2. PER-TOOL MODEL MATRIX (Model + Effort/Variant per Activity Profile)
#    Every tool defines its own mapping for the 4 standard profiles.
# ─────────────────────────────────────────────────────────────────────────────

[tools.kilo.profiles.deep-reasoning]
model = "google/gemini-4-argon"
variant = "high"
basis = "operator-stated"

[tools.kilo.profiles.orchestration]
model = "google/gemini-4-argon"
variant = "medium"
basis = "operator-stated"

[tools.kilo.profiles.bulk-execution]
model = "google/gemini-3.8-flash"
variant = "medium"
basis = "operator-stated"

[tools.kilo.profiles.exploration]
model = "google/gemini-3.8-flash"
variant = "low"
basis = "operator-stated"

[tools.claude.profiles.deep-reasoning]
model = "opus"
effort = "high"
basis = "operator-stated"

[tools.claude.profiles.orchestration]
model = "sonnet"
effort = "medium"
basis = "operator-stated"

[tools.claude.profiles.bulk-execution]
model = "sonnet"
effort = "medium"
basis = "operator-stated"

[tools.claude.profiles.exploration]
model = "haiku"
effort = "low"
basis = "operator-stated"

[tools.codex.profiles.deep-reasoning]
model = "gpt-5-codex"
effort = "high"
basis = "operator-stated"

# ─────────────────────────────────────────────────────────────────────────────
# 3. ACTIVITY ROUTING & CROSS-AGENT VERIFICATION DEFAULTS
#    Which tool + profile handles which stage by default
# ─────────────────────────────────────────────────────────────────────────────

[routing]
# Default executor when a task specifies a profile or defaults to bulk-execution
default_executor = "kilo"
default_profile = "bulk-execution"

[verification]
# Modes: "self" | "cross-agent" | "panel" | "owner"
default_mode = "cross-agent"
# Rule: when mode = "cross-agent", pick a verifier tool != task.executor
# If executor == "kilo" -> use "claude" (deep-reasoning); if executor == "claude" -> use "kilo" (deep-reasoning)
cross_agent_fallback_order = ["claude:deep-reasoning", "kilo:deep-reasoning", "codex:deep-reasoning"]
# Multi-engine review panel (for specs and high-risk tasks)
panel_reviewers = ["kilo:deep-reasoning", "claude:deep-reasoning", "codex:deep-reasoning"]
panel_require_blind_reviewer = true
```

---

### 2.2 Project-Level Override (`<project>/tasks/orchestration.toml` or `.ai-orchestration.toml`)

Example showing how `~/works/ricerca_auto` is expressed in ~35 lines of config (and generates the 105-line `ricerca_auto/AGENTS.md` deterministically):

```toml
[project]
name = "ricerca_auto"
primary_orchestrator = "kilo"   # Main session runs in Kilo (or "claude" / "any")

[routing]
default_executor = "kilo"

[verification]
default_mode = "cross-agent"

# Project-local domain skills & agents automatically listed in AGENTS.md Rule 1
[[project.domain_skills]]
name = "portal-scraper-builder"
path = ".kilo/skills/portal-scraper-builder/SKILL.md"
agent = ".kilo/agent/portal-scraper-builder.md"
when_to_use = "Delegating new portal scrapers under backend/scrapers/."

# Shared host resources NOT isolated by git worktrees (populates AGENTS.md Rule 3)
[project.isolation]
shared_databases = ["./data/car_search.db", "PostgreSQL :5433"]
shared_ports = [8765, 5433]
worker_port_range = [8766, 8779]
conflict_prone_files = ["backend/app.py", "frontend/index.html"]
zero_conflict_registries = ["backend/scrapers/registry.py"]

# Concrete Phase 5 Verification Commands per subsystem (populates AGENTS.md §3 & UI "Verify" button)
[project.verification_checks.backend]
description = "Verify module import, schema compatibility, and endpoint responses"
commands = ["PYTHONPATH=. .venv/bin/python -c \"import backend.app\""]

[project.verification_checks.scrapers]
description = "Verify registry auto-discovery and parser/classifier output"
commands = ["PYTHONPATH=. .venv/bin/python -c \"from backend.scrapers.registry import discover_scrapers; print(len(discover_scrapers()))\""]
```

---

## 3. Phased Delivery: Skill + Scripts First → CLI → Web UI / VS Code Extension

Following the same proven pattern used across the toolkit (`interactive-role-setup/scripts/validate_roles.py`, `gcube-repo-standards/scripts/check_alignment.py`, and `ai-swissknife`'s JSON CLI):

1. **Step 1 — Skill + Companion Python Scripts (Immediate, inside `ai-orchestration`)**:
   - The skill (evolving `interactive-role-setup` into `orchestration-setup`) guides the user interactively in chat to discover tools (`kilo`, `claude`, `codex`), MCP servers (`kilo-mcp`, `claude-mcp`), and models per activity profile, plus project-specific isolation/verification rules.
   - Companion stdlib-only Python scripts inside the skill (`scripts/manage_config.py`, `scripts/render_agents_md.py`, `scripts/tasks_engine.py`) handle all deterministic operations:
     - Read/merge/validate Global + Project `orchestration.toml`;
     - Render/update the project's `AGENTS.md` (producing the exact structure of `~/works/ricerca_auto/AGENTS.md`) and scaffold `tasks/`;
     - Parse/validate/transition task files and regenerate `tasks/00-INDEX.md`.
   - Every script outputs structured JSON on stdout (`--json`) and supports `--check` / `--apply`.
2. **Step 2 — Standalone CLI (`ai-orch`)**:
   - Thin CLI entry point wrapping those exact Python scripts for direct terminal and agent invocation.
3. **Step 3 — Web Server / UI & VS Code Extension (separate UI repo)**:
   - Calls the same Python core/CLI to inspect/edit `orchestration.toml`, view/edit tasks, launch runs via MCP, and trigger cross-agent verification.
