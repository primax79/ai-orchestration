# Naming Taxonomy & Coherence Plan (`ai-orchestration`, `kilo-mcp`, `claude-mcp`)

> **Goal:** Establish an organic, self-explanatory, collision-free naming scheme across **Core Skills**, **MCP Binding Skills & Agents**, **Scripts/CLI**, and **Configuration files**.

---

## 1. Diagnosis of Current Naming Inconsistencies

1. **`kilo-mcp` mixes `kilo-mcp-*` and bare `mcp-*` prefixes:**
   - `kilo-mcp-orchestrator`, `kilo-mcp-conflict-resolver`, `kilo-mcp-headless-executor`, `kilo-mcp-rag-explorer` use `kilo-mcp-*`.
   - **`mcp-metrics-analyst`** (skill) and **`mcp-orchestrator-agent`** (agent) use bare `mcp-*`—which fails to state *which* MCP server they belong to and will collide as soon as `claude-mcp` ships its own metrics skill or orchestrator agent.
2. **Core skill names in `ai-orchestration` reflect historical origins rather than current function:**
   - **`interactive-role-setup`**: no longer only maps 4 roles interactively; it manages the full Global + Project `orchestration.toml` (tools, MCPs, per-tool model matrix, verification modes) and renders the project's `AGENTS.md`.
   - **`macroplan-authoring`**: no longer only writes "macroplans"; it governs the entire `tasks/` pipeline (`00-INDEX.md`, `CONTEXT.md`, `specs/`, `NN-<slug>` initiatives, **and** `T###` emergent tasks + state transitions via `tasks_engine.py`).
   - **`task-delegation`**: sounds like the main delegation skill, whereas it is actually only the **git-worktree plumbing** helper (`apply_fix_to_worktree.sh`) for permission-blocked worktrees on the manual CLI path.
   - **`headless-executor-contract`**: applies to *every* delegated Executor session (including visible native `agent_manager` worktrees and subagents), not only headless background daemons.

---

## 2. Coherent Naming Taxonomy

### 2.1 Core Skills (`ai-orchestration` — Execution-Agnostic, Single- & Multi-Framework)

> **Status (`T010` — Approved & Applied):** Both the `kilo-mcp-*` binding prefix alignment (§2.2) and the core skill renames below (§2.1) have been approved and applied on disk across `ai-orchestration` and `kilo-mcp`.

Organized around three clear prefixes: **`orchestration-*`** (system setup, workflow loop, metrics), **`task-*`** (task pipeline, spec authoring, worktree ops), and **`executor-*` / `conflict-*`**:

| Historical Name | Active Coherent Name | Plugin | Companion Script | Role |
| --- | --- | --- | --- | --- |
| `interactive-role-setup` | **`orchestration-setup`** | `shared` | `scripts/orchestration_config.py`, `scripts/validate_roles.py` | Configures Global + Project `orchestration.toml` (tools, MCPs, models per profile, verification modes) and renders `AGENTS.md`. |
| `orchestration-methodology` | **`orchestration-workflow`** | `architect-side` | — | The 6-phase Architect/Executor loop (Discovery, Isolation, Delegation, Monitoring, Verification, Closure) for both native sub-sessions and MCP. |
| `delegation-roi-analysis` | **`orchestration-metrics`** | `architect-side` | — | Evaluates delegation ROI, decision branches, bounce/cancel/discard rates, and spec-guardrail feedback loop. |
| `macroplan-authoring` | **`task-pipeline`** | `architect-side` | `scripts/tasks_engine.py` | Manages the `tasks/` directory (`00-INDEX.md`, `CONTEXT.md`, `specs/`, `NN-<slug>` initiatives, `T###` emergent tasks, and state machine). |
| `task-spec-authoring` | **`task-spec-authoring`** *(unchanged)* | `architect-side` | — | Authors unambiguous task specs & `## Verification` criteria (negative-claim rule, drift defense, caller tracing, parallel batch scoping, review panels). |
| `task-delegation` | **`task-worktree-ops`** | `architect-side` | `scripts/apply_fix_to_worktree.sh` | Git-worktree operational safety and git-plumbing fix application when direct file-edit tools are permission-blocked. |
| `conflict-resolver` | **`conflict-resolver`** *(unchanged)* | `architect-side` | — | Resolves merge conflicts between parallel Executor branches (mechanical vs. incompatible-design fork). |
| `headless-executor-contract` | **`executor-contract`** | `executor-side` | — | Behavioral contract for any delegated Executor session (native worktree/subagent or MCP): zero interactivity, `focus_files`, 1-task-1-commit, `Final Report`. |

---

### 2.2 MCP Binding Skills & Agents (`kilo-mcp`, `claude-mcp`)

Rule: **Every artifact bound to `<tool>-mcp` uses the `<tool>-mcp-` prefix** (`kilo-mcp-*`, `claude-mcp-*`).

| Core Template (`ai-orchestration`) | `kilo-mcp` Artifact Name | `claude-mcp` Artifact Name | Old `kilo-mcp` Name |
| --- | --- | --- | --- |
| `orchestration-workflow` | **`kilo-mcp-orchestrator`** | `claude-mcp-orchestrator` | `kilo-mcp-orchestrator` |
| `orchestration-metrics` | **`kilo-mcp-metrics`** *(or `kilo-mcp-metrics-analyst`)* | `claude-mcp-metrics` | `mcp-metrics-analyst` ❌ |
| `conflict-resolver` | **`kilo-mcp-conflict-resolver`** | `claude-mcp-conflict-resolver` | `kilo-mcp-conflict-resolver` |
| `executor-contract` | **`kilo-mcp-executor-contract`** | `claude-mcp-executor-contract` | `kilo-mcp-headless-executor` |
| *(Kilo RAG exploration)* | **`kilo-mcp-rag-explorer`** | *(n/a)* | `kilo-mcp-rag-explorer` |
| *(Autonomous runner agent)* | **`kilo-mcp-orchestrator-agent`** | `claude-mcp-orchestrator-agent` | `mcp-orchestrator-agent` ❌ |

---

### 2.3 MCP Server Tools Naming Symmetry (`kilo-mcp` ↔ `claude-mcp`)

| Lifecycle Stage | `kilo-mcp` Tool | `claude-mcp` Tool |
| --- | --- | --- |
| Discovery (Models / Auth / Agents / Skills) | `kilo_list_models`, `kilo_auth_status`, `kilo_list_agents`, `kilo_list_skills` | `claude_list_models`, `claude_auth_status` |
| Semantic Search (RAG) | `kilo_rag_search` | *(n/a)* |
| Worktree Isolation | `kilo_create_worktree`, `kilo_workspace_status` | `claude_workspace_status` (`-w` native on implement) |
| Dispatch Implementation | `kilo_implement` | `claude_implement` |
| Live Progress / Wait / Result / Cancel | `kilo_task_progress`, `kilo_task_wait`, `kilo_task_result`, `kilo_task_cancel`, `kilo_task_status` | `claude_task_progress`, `claude_task_wait`, `claude_task_result`, `claude_task_cancel` |
| Session Steering / Checkpoints | `kilo_session_revert`, `kilo_session_fork`, `kilo_respond_question`, `kilo_get_session_todo`, `kilo_update_session_todo` | *(via `continue_session_id`)* |
| Verification & Telemetry | `kilo_verify_worktree` *(planned)*, `kilo_log_issue`, `kilo_log_decision` *(planned)*, `kilo_metrics` | `claude_log_issue`, `claude_log_decision`, `claude_metrics` *(Phase 5)* |
