# T018 Precedence Analysis: `orchestration-workflow` vs `kilo-mcp-orchestrator`

**Context:** Analysis for Q003 and T018. Compares the generic skill (`orchestration-workflow`, this repo, abbreviated **OW**) and its bound counterpart (`kilo-mcp-orchestrator` in `kilo-mcp`, abbreviated **KMO**). Evaluates whether the trigger conflict flagged in `tasks/env-doctor/notes/T016-report.md` represents substantive incompatibility and proposes precedence rules.

---

## 1. Relationship: Specialization vs Contradiction

KMO is a direct code generation artifact of OW via `scripts/generate_binding.py` using `kilo-mcp/bindings/orchestration-workflow.json`. Substantively, KMO is a concrete tool specialization of OW's protocol-agnostic lifecycle.

### Overlapping Advice (Same Advice, Tool-Parameterized)
- **Role Discipline:** Delegate, do not implement; minor verification fixes in worktree allowed, logic fixes bounced back (OW:30-48 vs KMO:21-39).
- **Phase 2 Isolation:** Default unisolated hazard; live git race incident; `isolation='worktree'`; shared host resources (ports, containers); repo-level `.git/config` hazard; record `branch` and `worktree` on task (OW:56-97 vs KMO:43-62).
- **Phase 3 Delegation:** Non-blocking background dispatch; pass focus files and skills; break multi-session work into `tasks/` pipeline (OW:98-108 vs KMO:63).
- **Phase 5 Verification & 5b Integration:** Never trust Final Report alone; execute backend/frontend/schema/infra; post-merge consuming application build (OW:139-152, 183-188 vs KMO:71-77, 78-83).
- **Phase 6 Closure:** Explicit checkout sequence before merge; clean up worktrees on all terminal paths (OW:191-203 vs KMO:85-96).
- **Methodology Blocks (Verbatim Identical):**
  - 7 Economic Rules & Model Pricing Matrix (OW:204-260 vs KMO:98-154).
  - Specification rigor for analysis/exploration requests (OW:261-313 vs KMO:155-207).
  - Mid-session emergent work capture in `tasks/` (OW:314-346 vs KMO:208-240).
  - Blocking questions filed via `ai-orch questions ask` (OW:347-365 vs KMO:241-259).

### Covered Only by Bound (KMO)
- Concrete tool calls: `kilo_rag_search`, `kilo_implement`, `kilo_task_wait`, `kilo_task_progress`, `kilo_task_cancel`, `kilo_session_revert`, `kilo_log_issue`, `kilo_log_decision` (KMO:42, 63-70, 84).
- Host PID watcher shell fallback: `while kill -0 <pid>...` (KMO:69).
- Agent Manager automatic registration behavior in `.kilo/agent-manager.json` (KMO:262).
- Offline diagnostic scripts: `diagnose-kilo-tasks.sh`, `kill-kilo-task.sh` (KMO:264-267).

### Covered Only by Generic (OW) — Omitted in KMO due to Template Override Drift
- Single-Framework Native vs Multi-Framework execution modes (OW:14-15, 23-28).
- Phase 1 check frequency constraint: `"once per session or after a dispatch failure"` (OW:54-56).
- Phase 4 on-branch delivery annotation: `"- state: delivered with verification pending: <command>"` (OW:134-138).
- Phase 5 Verification Modes (`independent-session`, `cross-agent`, `panel`, `owner`, `self`) (OW:153-170).
- Phase 5 Post-Verification Decision Table: Merge, Fix inline (`<= 5` lines), Bounce (`> 5` lines), Stop and ask user (OW:172-182).
- Scaffolding risk check: removing rogue harness configuration injected by generators (OW:367-381).
- Unified 10-state task lifecycle table: `"Track task state as a path, not a label"` (OW:383-407).

### Contradictions / Behavioral Divergence
1. **Phase 4 Completion Polling vs Deterministic Wait:**
   - OW (line 111): *"Small, well-scoped tasks: a single final-result check is enough."* (Assumes asynchronous notification or completion check).
   - KMO (lines 65, 69): *"await completion deterministically with `kilo_task_wait` ... Prefer `kilo_task_wait(task_id=...)` to block until the task completes ... or zero-token OS PID watcher"*.
   - *Impact:* KMO prescribes synchronous blocking inside the turn, whereas OW encourages leaving the turn unblocked.
2. **Phase 1 Health Check Cadence:**
   - OW (lines 54-56): *"Confirm the Executor's engine ... once per session or after a dispatch failure (do not re-run health/config checks before every single task)."*
   - KMO (line 42): *"Use `kilo_list_models` and `kilo_auth_status` to ensure Kilo's engine and models are ready"* (no frequency restriction, causing redundant calls).

---

## 2. Trigger Overlap

### Description Comparison
- **OW (line 3):** `"...Use when coordinating development work delegated to another agent, or when new tasks appear during a working session."`
- **KMO (line 3):** `"...Use when coordinating development work through the kilo-mcp tools, or when new tasks appear during a working session."`

### Loading Scenarios
- **Agent loads OW only:** When coordinating native subagents/worktrees (no MCP), or delegating to non-Kilo agents (Codex, Claude-in-Claude).
- **Agent loads KMO only:** When user prompt explicitly references Kilo or `kilo-mcp` tools.
- **Agent loads BOTH (Conflict):** Whenever the user asks to "delegate this task", "coordinate worktrees", or "capture this new emergent task". Both skills claim the identical trigger clause `"or when new tasks appear during a working session"`, causing Claude to either load both into context (wasting ~12k tokens on duplicate economic tables) or choose arbitrarily.

---

## 3. Verdict

**Incompatible only in wording/trigger, fully compatible in substance.**
KMO is not an alternative orchestration philosophy; it is the concrete `kilo-mcp` binding of OW. The differences stem entirely from concrete tool bindings plus accidental template override omissions in `bindings/orchestration-workflow.json`.

---

## 4. Proposal: Precedence Rules & Doctor Acknowledgment

### Concrete Text for `orchestration-workflow`
Add under `## Quick Reference` / `## Role discipline`:
```markdown
### Precedence with Bound Skills
If `kilo-mcp-orchestrator` is also loaded and the execution channel is Kilo via `kilo-mcp`, defer tool-level invocation details (e.g. `kilo_implement`, `kilo_task_wait`, `kilo_rag_search`, `kilo_log_issue`) to `kilo-mcp-orchestrator`. All architectural rules—the 6-phase lifecycle, verification modes (`independent-session`, `cross-agent`, etc.), the Post-Verification Decision Table, formal task states (`open` → `delivered` → `verified` → `done`), and economic rules—remain authoritative as defined here.
```

### Concrete Text for `kilo-mcp-orchestrator`
Add under `## Quick Reference` / `## Role discipline`:
```markdown
### Precedence with Generic Skills
This skill provides the concrete `kilo-mcp` tool bindings for orchestrating Kilo. When `orchestration-workflow` is also loaded, this skill specializes the tool calls (`kilo_implement`, `kilo_task_wait`, etc.), while `orchestration-workflow` governs the overarching architecture: task state transitions, verification modes, the Post-Verification Decision Table, and harness safety.
```

### Description Adjustments to Stop Trigger Competition
- **OW Description:**
  `"Orchestrate an Executor agent through the Architect/Executor pattern - discovery-first exploration, isolation before delegating, non-blocking parallel delegation, complexity-scaled monitoring/intervention, real verification, defect telemetry, and capture of emergent tasks. Use for native subagent/worktree orchestration or multi-framework pipelines. When delegating specifically to Kilo via kilo-mcp tools, prefer kilo-mcp-orchestrator."`
- **KMO Description:**
  `"Tool-level binding for orchestrating Kilo via the kilo-mcp server - kilo_rag_search, kilo_implement with worktree isolation, deterministic wait (kilo_task_wait), progress monitoring, and defect telemetry (kilo_log_issue). Use specifically when executing tasks through kilo-mcp tools. For generic multi-agent coordination or native worktrees, use orchestration-workflow."`

### Environment Doctor Handling
The Doctor currently treats generic + bound as an unresolvable red `trigger-conflict` under policy `claude=bound` (T016:26, 126-134). The Doctor should classify the pair as **`acknowledged` (info severity, not an error)** when:
1. Both skills carry reciprocal precedence declarations (or the Doctor verifies that KMO is a declared binding of OW via `bindings/orchestration-workflow.json`).
2. The user has acknowledged cohabitation in `~/.config/ai-orchestration/doctor-ack.json`.
Disabling `architect-side@ai-orchestration` must never be advised, as it strips 5 essential non-conflicting skills (`task-pipeline`, `task-spec-authoring`, `task-worktree-ops`, `conflict-resolver`, `orchestration-metrics`).

---

## 5. Mandatory Textual Fixes (Independent of Precedence)

1. **Restore Core Architecture in `kilo-mcp/bindings/orchestration-workflow.json`:**
   Refactor `SKILL.template.md` so that `phase5_body` overrides do not wipe out Verification Modes (OW:153-170) and the Post-Verification Decision Table (OW:172-182), and `closing` overrides do not wipe out the 10-state table (OW:383-407) and harness scaffolding checks (OW:367-381).
2. **Align Health-Check Frequency:**
   Add `"once per session or after a dispatch failure"` to KMO Phase 1 (KMO:42) to match OW:54-56 and prevent wasteful model/auth polling.
3. **Restore On-Branch Delivery Annotation:**
   Include the rule requiring `- state: delivered` with `verification pending:` on the worktree branch (OW:134-138) in KMO Phase 4.
4. **Harmonize Completion Polling vs Wait:**
   Clarify in KMO:65,69 that `kilo_task_wait` is recommended when running in an interactive host that supports blocking MCP calls, while non-blocking delegation with detached monitoring applies to CLI/headless workflows.
