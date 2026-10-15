# Project-Level Orchestration Bootstrap (`AGENTS.md` Pattern from `ricerca_auto`)

> **Source analyzed:** `~/works/ricerca_auto/AGENTS.md`, `.kilo/skills/portal-scraper-builder/SKILL.md`, `.kilo/agent/portal-scraper-builder.md` (2026-10-15)

---

## 1. Why `ricerca_auto/AGENTS.md` Works So Well

Looking at `~/works/ricerca_auto/AGENTS.md` reveals a crucial architectural truth about how coding agents (Claude Code, Kilo Code) actually behave:

1. **Skills are passive (opt-in on trigger); `AGENTS.md` is always-on (injected at turn 0).**
   - If the rule *"You are the Architect: keep the main session free, never implement inline, delegate via `agent_manager`/`task`/`kilo_implement`"* lives **only** inside a skill (`orchestration-methodology`), the main session might start editing files directly before ever loading the skill.
   - Placing the **Orchestration Charter** directly in the project's `AGENTS.md` guarantees that from the very first message of any session, the agent knows its role (Architect/Orchestrator), its execution channels, and its constraints.

2. **It bridges the gap between Generic Skills and Project Ground Truth.**
   Abstract skills (`orchestration-methodology`, `task-spec-authoring`, `interactive-role-setup`) state general principles (*"isolate shared host resources"*, *"use disjoint write scopes"*, *"pick the model matching the role profile"*, *"run real verification"*). `ricerca_auto/AGENTS.md` **instantiates** each abstract rule with the project's concrete parameters:

| Abstract Rule in Skill | Concrete Instantiation in `ricerca_auto/AGENTS.md` |
| --- | --- |
| **Role discipline** (`orchestration-methodology`) | Main session = Architect only; delegate to `agent_manager` (`worktree`/`local`) or `task` (`explore`/`general`). Inline fix allowed only in Phase 5 for ≤5-line typo/import. |
| **Disjoint parallel write scopes** (`task-spec-authoring`) | Shared files named explicitly (`backend/app.py`, `frontend/index.html`); parallel tasks use the zero-conflict plugin registry (`backend/scrapers/registry.py`). |
| **Execution mode selection** (`orchestration-methodology` + native Kilo tools) | Decision table mapping **Isolated Git Worktree** (`agent_manager mode="worktree"`), **Subagent** (`task`), and **Local Session** (`agent_manager mode="local"`). |
| **Shared host resource isolation** (`orchestration-methodology` Phase 2) | Names the exact resources worktrees share: `./data/car_search.db`, PostgreSQL `:5433`, uvicorn `:8765`, `.git/config`. |
| **Role-to-model mapping** (`interactive-role-setup`) | Maps `deep-reasoning`, `orchestration`, `bulk-execution`, `exploration` to concrete models + variants (`google/gemini-4-argon` `high`/`medium` vs `google/gemini-3.8-flash` `medium`/`low`). |
| **Phase 5 real verification** (`orchestration-methodology` Phase 5) | Lists the exact runnable checks per subsystem (`PYTHONPATH=. .venv/bin/python -c "import backend.app"`, scraper registry check, frontend/backend contract check). |
| **Project-local Executor skill & agent** (Review §4.3) | `.kilo/skills/portal-scraper-builder/SKILL.md` + `.kilo/agent/portal-scraper-builder.md` — a domain-specific Executor contract with zero-conflict file scope and an evolution-proposal escape hatch (`docs/scraper_proposals/<portal_id>.md`). |

---

## 2. Two Additional Patterns in `ricerca_auto` Worth Promoting to `ai-orchestration`

### 2.1 Multi-Channel Execution Table (Native `agent_manager` / `task` vs. MCP `kilo_implement` / `claude_implement`)
Until now, `kilo-mcp-orchestrator` assumed delegation always goes through the `kilo-mcp` MCP server (`kilo_implement`), while `task-delegation` assumed manual CLI git worktrees.
`ricerca_auto/AGENTS.md` (Rule 3) captures the **third, native execution channel** when the orchestrator is running inside Kilo Code (or Claude Code) itself:
- **Worktree session**: `agent_manager(mode="worktree")` (or `claude --worktree` / `kilo_implement(isolation="worktree")`) for parallel multi-file code changes.
- **Subagent (`task`)**: `subagent_type="explore"` or `"general"` (`background=true/false`) for read-only discovery, caller tracing, **blind spec/code review**, or strictly isolated single-file creation when no other git writer is active.
- **Local session**: `agent_manager(mode="local", worktreeID=...)` to steer or follow up inside an existing managed worktree.

### 2.2 The "Zero-Conflict Evolution Proposal" Pattern for Parallel Executors
In `.kilo/skills/portal-scraper-builder/SKILL.md` (Step 4):
- Parallel Executor agents are strictly forbidden from editing shared core files (`backend/models.py`, `backend/app.py`).
- When an Executor discovers new data or needs a core schema extension while working on its isolated plugin, it:
  1. Stores the raw data in an extensible dict (`portal_extras`);
  2. Writes a structured proposal file in an isolated path (`docs/scraper_proposals/<portal_id>.md` or an emergent task `tasks/<category>/T###-...`) for the Architect to review and integrate later.
- This completely eliminates the #1 cause of parallel Executor merge conflicts and scope creep.

---

## 3. How to Manage This Cleanly Across Projects (Without Drift)

Having a document like `ricerca_auto/AGENTS.md` in every orchestrated project is the right starting point, **provided we solve three management issues**:

### Issue 1: Model Drift Across Projects (Rule 4)
If 10 projects hardcode `Gemini 4 Argon` and `Gemini 3.8 Flash` inside their `AGENTS.md`, changing your model lineup requires editing 10 repositories.
- **Solution:**
  - Keep the **Role Profile table** in `AGENTS.md` (describing what falls under `deep-reasoning`, `orchestration`, `bulk-execution`, `exploration` in *this* project),
  - Either resolve the concrete model/variant dynamically from `~/.config/ai-architect-executor/roles.toml` (via CLI/UI), **or** mark the `Recommended Model & Variant` column in `AGENTS.md` with a managed block (`<!-- BEGIN ai-orchestration:roles --> ... <!-- END ai-orchestration:roles -->`) that the `ai-orch` CLI / Web UI can refresh across all projects in one command when `roles.toml` changes (identical to how `vscode-mcp-dap-debugger` manages its block in `AGENTS.md`!).

### Issue 2: Separating Boilerplate Methodology from Project-Specific Parameters
Notice that ~50% of `ricerca_auto/AGENTS.md` is universal orchestration rules (Rule 1, Rule 2.1/2.4/2.5, Section 3 merge sequence) and ~50% is project-specific configuration:
- Project-specific **Shared Host Resources** (DB paths, ports, Docker containers)
- Project-specific **Shared / Conflict-Prone Files & Registry Entrypoints** (`backend/app.py`, `frontend/index.html`, `backend/scrapers/registry.py`)
- Project-specific **Verification Commands** per component (`backend/`, `scrapers/`, `frontend/`)
- Project-specific **Domain Skills / Subagents** (`portal-scraper-builder`)

- **Solution:** Define a **Canonical `AGENTS.md` Orchestration Template** in `ai-orchestration` (with `<!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration -->` markers or a companion `tasks/CONTEXT.md`), plus a **`project-orchestration-setup` skill / `ai-orch init` command** that:
  1. Analyzes the target repo (detects DBs, ports in `compose.yml`/`.env`/code, entrypoints, test/build commands, existing `.kilo/` or `.claude/` skills);
  2. Reads `~/.config/ai-architect-executor/roles.toml` (and queries `agent_manager_models` / `kilo_list_models`);
  3. Generates the tailored `AGENTS.md` + initializes `tasks/` (`00-INDEX.md`, `CONTEXT.md`, `AGENTS.md`).

### Issue 3: Synchronizing `AGENTS.md` with the Python Server / Web UI
Because the project-specific sections of `AGENTS.md` (ports, DBs, verification commands, role-to-model table, required skills) follow a predictable structure, the **Python Orchestration Server & Web UI** can:
- **Read** those sections from the project's `AGENTS.md` / `tasks/CONTEXT.md` to pre-populate the UI (e.g., knowing which verification commands to run in Phase 5, which ports to assign to parallel worktrees, and which default model to select for a `bulk-execution` vs `deep-reasoning` task);
- **Edit / Regenerate** the managed orchestration block in `AGENTS.md` directly from the Project Settings tab of the Web UI.
