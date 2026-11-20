# ricerca_auto — Project Architecture & Notes

Project-specific domain rules and scraper notes that must remain intact.

<!-- BEGIN ai-orchestration -->
# Agent Orchestration & Development Guidelines (`AGENTS.md`)

> **Managed by `ai-orchestration` (`orchestration_config.py render-agents-md`).**
> Edit `/Users/Alfredo/.config/ai-orchestration/projects/ricerca_auto/orchestration.toml` (project) or `/Users/Alfredo/.config/ai-orchestration/orchestration.toml` (global) and re-run `render-agents-md --apply` to update.

This repository uses an **Architect / Executor** development workflow (`primary_orchestrator = "claude"`, `default_executor = "kilo"`, `verification_mode = "cross-agent"`). The **main session** acts primarily as the **Architect & Orchestrator** (discovery, task specification, parallel dispatch, verification, and integration), delegating larger implementation work and heavy exploration to isolated **Worktree sessions** and **Subagents**.

---

## 1. Required Skills

Load and follow these skills whenever planning, delegating, executing, or reviewing work:

- **`orchestration-workflow`** (or **`kilo-mcp-orchestrator`** when driving via MCP) — Core 6-phase Architect/Executor loop (Discovery → Isolation → Delegation → Monitoring → Verification → Closure & Merge).
- **`task-spec-authoring`** — Authoring unambiguous, grounded task specs (`focus_files`, caller tracing, negative-claim rule, disjoint parallel write scopes, one-task-one-commit, risk-calibrated verification).
- **`task-pipeline`** — Structuring multi-task initiatives, specs, and emergent mid-session tasks inside `tasks/` (`00-INDEX.md`, `CONTEXT.md`, `specs/`, `NN-<slug>/plan.md`, `T###-<slug>`).
- **`task-worktree-ops`** — Operational git/worktree mechanics for inspecting, fixing, and merging Executor worktrees safely without racing active sessions.
- **`executor-contract`** — Behavioral contract for all delegated Executor sessions (zero interactivity, strict scope adherence, real verification before reporting, structured `Final Report`).
- **`conflict-resolver`** — Resolving merge conflicts across parallel Executor branches while preserving the semantics of each feature.
- **`orchestration-setup`** — Mapping abstract role profiles (`deep-reasoning`, `orchestration`, `bulk-execution`, `exploration`) to concrete models and reasoning variants.

---

## 2. Core Operating Rules

### Rule 1: Focus the Main Session on Architecture & Orchestration

- The main session focuses on **analyzing requirements, designing task specs, orchestrating execution, and evaluating/verifying results** with the user.
- **Prefer delegating multi-file implementations, large refactors, or parallel tasks** to isolated worktrees or subagents to keep the main session context clean and focused. Small, direct adjustments and surgical edits may be performed in the main session when appropriate.
- **Capture emergent work immediately:** If a bug, follow-up, or side requirement surfaces mid-conversation and won't be finished in the current turn, record it in `tasks/` (`task-pipeline`) and update `tasks/00-INDEX.md` before continuing. Keep the main session's context lean.
- **Register as Orchestrator & Heartbeat:** When orchestrating in a workspace with `ai-orch` installed, register this session with `ai-orch sessions register --role orchestrator` and send periodic heartbeats (`ai-orch sessions heartbeat <session_id>`). Interactive sessions (e.g. Claude Code) do not send automatic heartbeats: emit a heartbeat on each turn or periodic check. Note that a "stale" status for an active interactive holder indicates idle time between prompts, not absence.

### Rule 2: Define Execution Tasks Before Delegating

Every delegated unit of work must have a well-defined specification (inline in the delegation prompt for a single self-contained task, or as a task file in `tasks/` for multi-step/parallel initiatives) containing:

1. **Goal & Non-Goals:** Exact outcome expected and explicit exclusions to prevent scope creep.
2. **Grounded `focus_files` & Callers:** Real file paths and symbol/line references verified via `grep`/`read` (never guessed). Instruct the Executor to re-`grep` if line numbers may have shifted. Trace all callers of any modified function or API route.
3. **Disjoint Write Scope (for Parallel Batches):**
   - Assign each parallel task an explicit, non-overlapping file/directory scope.
   - If multiple tasks must touch a shared file, either serialize those tasks, pre-assign exact sections/symbols.
4. **One Task = One Commit:** Instruct the Executor to create a single, atomic commit scoped strictly to its task.
5. **Runnable Verification Criteria:** Concrete commands the Executor must run before reporting `delivered`. If correctness relies on a **negative claim** ("X is unused / dead code"), mandate a full regression check across the codebase.

### Rule 3: Delegate Maximum Work & Evaluate Worktree vs. Local/Subtask Isolation

Before dispatching, explicitly evaluate whether the task requires **Git Worktree isolation** or can run as a **same-tree Subagent / Local session**:

| Execution Mode | Tool / Mechanism | When to Use |
| :--- | :--- | :--- |
| **Isolated Git Worktree** *(Default for parallel code changes)* | `kilo_implement(isolation="worktree")` | Parallel implementation tasks modifying tracked files; multi-file features or refactors; comparing alternative implementations; long-running implementation work while keeping the main session clean. |
| **Background / Foreground Subagent** *(Read-only or strictly disjoint single-file work)* | `Agent` | Codebase discovery, caller tracing, architectural analysis, **independent blind review of a draft spec or delivered task**, or strictly isolated single-file creation when no other git writer is active. |
| **Local / Follow-up Session** | `kilo_implement(continue_session_id=...)` | Follow-up steering inside an already-created worktree or single sequential task when explicitly requested in the current checkout. |

**Isolation Safety Checks (Shared Host Resources Are NOT Isolated by Worktrees):**

- **Never run concurrent code-modifying tasks in the same working tree** unless their write scopes are 100% file-disjoint and neither runs git mutations while the other is active. When in doubt, use worktree isolation.
  - **Git Config (`.git/config`):** Shared across all worktrees. Delegated tasks must never run `git config` or install hooks automatically.

### Rule 4: Select the Right Model & Reasoning Effort per Task

When dispatching tasks, explicitly select the `model` and reasoning effort/variant matching the task's role profile (configured in `orchestration.toml`):

| Role Profile | Configured Model & Variant / Effort | Typical Tasks |
| :--- | :--- | :--- |
| **`deep-reasoning`** *(High complexity / silent-failure risk)* | **claude**: `opus` (`high`)<br>**kilo**: `google/gemini-4-argon` (`high`)<br>**codex**: `gpt-5-codex` (`high`) | Complex multi-file architecture & core logic, tricky bug root-cause analysis, blind spec/code review (`task-spec-authoring`), and semantic merge-conflict resolution (`conflict-resolver`). |
| **`orchestration`** *(Planning, dispatch & verification)* | **claude**: `sonnet` (`medium`)<br>**kilo**: `google/gemini-4-argon` (`medium`)<br>**codex**: `gpt-5-codex` (`medium`) | Main session task decomposition, spec drafting, integration verification, and evaluating Executor outputs. |
| **`bulk-execution`** *(Well-specified implementation)* | **claude**: `sonnet` (`medium`)<br>**kilo**: `google/gemini-3.8-flash` (`medium`)<br>**codex**: `gpt-5-codex-mini` (`medium`) | Executing self-contained task specs with clear `focus_files`, isolated modules/plugins, UI adjustments, and unit/smoke tests. |
| **`exploration`** *(Fast read-only discovery & checks)* | **claude**: `haiku` (`low`)<br>**kilo**: `google/gemini-3.8-flash` (`low`)<br>**codex**: `gpt-5-codex-mini` (`low`) | Fast codebase search (`explore` / RAG), caller tracing, catalog/JSON inspection, and running read-only verification checks. |

---

## 3. Orchestration Lifecycle & Cross-Agent Verification Gate

Track every task through explicit states (`open` → `in progress` → `delivered` → `verified` → `done`). **An Executor can only mark a task `delivered`; `verified` must be set by someone other than the Executor (or after explicit owner approval recorded in `PROGRESS.md`).**

1. **Discover:** Use fast read-only searches (`grep`, `glob`, `read`, or exploration subagents/RAG) to gather ground-truth context.
2. **Specify & Dispatch:** Write the task spec(s) and launch non-blocking parallel sessions.
3. **Monitor & Intervene:** Monitor progress (or await via `kilo_task_wait` / background completion watcher). If a session drifts off-spec or stalls, cancel/stop early and steer the same session.
4. **Verify Independently (Default mode: `cross-agent`, fallback order: `claude:deep-reasoning`, `kilo:deep-reasoning`, `codex:deep-reasoning`):**
   - Never trust the Executor's `Final Report` alone. Inspect `git status` and `git diff` in the Executor's worktree.
   - Re-run the task's Verification checks (directly or by dispatching an independent **Cross-Agent Verifier != Executor** on the `deep-reasoning` profile):
     - Run the project's build, lint, and test commands against a disposable environment.
   - If any criterion fails, mark the task `bounced` and send the exact failing criterion / `B1..Bn` findings back to the **same** Executor session.
5. **Integrate & Clean Up:**
   - Always checkout the target integration branch explicitly before merging:
     `git status --short` → `git checkout <target-branch>` → `git merge --no-ff <task-branch> -m "Merge <task-id>: <summary>"` → `git log --oneline --graph -5`.
   - **Post-Merge Integration Gate:** Run lint, tests, and a full consuming build on the integrated tree.
   - Remove completed worktrees (`git worktree remove <path>`) on merge, cancellation, or discard.
<!-- END ai-orchestration -->

## Project Database Notes

PostgreSQL port 5432; keep this footer byte-for-byte.
