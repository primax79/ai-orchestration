# Gap Analysis and Evolution Roadmap

> **Sources analyzed:**
> - `../architect-executor-consolidated-review.md` (787 lines, external consolidated review)
> - `../task-completion-notification-spec.md` (119 lines, completion notification & watcher spec)
> - `../interactive-role-setup-spec.md` (212 lines, role setup spec)
> - `../claude-mcp/SPEC.md` & `../claude-mcp/reviews/001-spec-review-kilo-gemini-3.7-flash.md`
> - `../status/handoff-2026-10-08-emergent-tasks-convention.md` & `../tasks/00-INDEX.md`

---

## 1. What Has Already Been Resolved (Completed Evolutions)

Cross-checking the current repository state against `architect-executor-consolidated-review.md` and the specs in the workspace root shows that **all Tier 1 structural issues and all of Part 5** have already been implemented and shipped:

| Review / Spec Item | Status | How It Was Resolved in the Repos |
| --- | --- | --- |
| **1.1 Near-duplicate repos (`ai-architect-executor` vs `kilo-mcp`)** | ✅ **Done** | Implemented Option (b) *"Generate, don't duplicate"*: `ai-architect-executor/scripts/generate_binding.py` + `SKILL.template.md` + `kilo-mcp/bindings/*.json` + `regenerate_bound_skills.py --check`. READMEs also explicitly forbid installing both alongside each other. |
| **1.2 Split into `architect-side` and `executor-side` plugins** | ✅ **Done** | Both `ai-architect-executor` and `kilo-mcp` are split into `plugins/architect-side/` and `plugins/executor-side/` (plus `plugins/shared/` in `ai-architect-executor`). |
| **1.3 & 4.1 Dangling `kilo-task-delegation` & path-independent spec rules** | ✅ **Done** | Extracted into `ai-architect-executor/plugins/architect-side/skills/task-spec-authoring/SKILL.md` (includes negative-claim rule, reference drift, caller tracing, multi-engine blind/primed review panel, parallel batch rules). `task-delegation` narrowed to manual/CLI git-worktree mechanics. |
| **1.3 & 4.2 Dangling `macroplan-authoring` reference** | ✅ **Done** | `macroplan-authoring` lives in `agentic-coding-kit` (`common-tools` v0.3.1), expanded with the **Emergent Tasks** convention (`T###`, `00-INDEX.md`, `owner-session`), and is declared in `plugins/architect-side/dependencies.json`. |
| **2.1 Consumer path leak (`gcube_atlas/plans/...`)** | ✅ **Done** | Removed from `task-spec-authoring` / `task-delegation`; genericized to *"a cross-file conversion macroplan, roughly 110 call sites across seven files"*. |
| **3.5 Bug in `scripts/apply_fix_to_worktree.sh` (`set -euo pipefail` on clean worktree)** | ✅ **Done** | Fixed and paired with regression test suite `scripts/test_apply_fix_to_worktree.sh`. |
| **Part 5 (5.1–5.4) Role profiles, `interactive-role-setup`, `validate_roles.py`** | ✅ **Done** | Implemented in `ai-architect-executor/plugins/shared/skills/interactive-role-setup/`, `skill-requirements.json` across all plugins, and `validate_roles.py` wired into `generate_skill_indices.py`. |

---

## 2. Open Gaps & Pending Evolutions

The remaining items from the consolidated review, the task-completion notification spec, and the workspace investigations fall into **three actionable tracks**:

### Track A — Methodology & Skill Refinements (`ai-architect-executor` → `kilo-mcp`)

1. **Task Completion Notification — Watcher Remedy in Skills (`task-completion-notification-spec.md` Part 2)**
   - *Gap*: `orchestration-methodology` and `kilo-mcp-orchestrator` mention `ScheduleWakeup` in Phase 4, but do not yet encode the validated background PID-watcher pattern (`while kill -0 <pid> 2>/dev/null; do sleep 10; done; echo "task <name> finished"`) for hosts/sessions where background shell notifications wake the orchestrator immediately, nor the `kilo_task_wait` flow once Part 1 lands.
2. **Phase 5 Explicit 3-Way Decision Point & Worktree Cleanup on Cancellation (Review §2.2, §2.7)**
   - *Gap 1*: The explicit criteria for choosing between **merge / fix inline / bounce back to Executor / stop and ask user** live in `mcp-orchestrator-agent.md` ("When to stop and ask the user") instead of at the end of Phase 5 in `orchestration-methodology/SKILL.template.md` where interactive orchestrators need them most.
   - *Gap 2*: Phase 6 specifies `git worktree remove` only after a successful merge. Phase 4 cancellation leaves `.kilo/worktrees/<branch>` and dead branches behind. Closure rules are needed for every terminal outcome (`merged`, `cancelled`, `discarded`).
   - *Gap 3*: Phase 1 says to run model/auth checks (`kilo_list_models`, `kilo_auth_status`) "before dispatching anything", which if read literally wastes tool calls on every delegation instead of once per session or on failure.
3. **`conflict-resolver` Rework (Review §2.5)**
   - *Gap*: Currently a 22-line stub that says *"You have been invoked by the Architect"* (wrong audience: the Architect resolves conflicts during Phase 6) and instructs to *"preserve the semantics of both"*. When two parallel tasks make **incompatible design changes** (e.g. different helper signatures or competing abstractions), preserving both ships broken architecture that compiles. Needs to:
     - Re-target at the Architect;
     - Distinguish mechanical conflicts (imports, barrel exports) from incompatible-design conflicts (stop, pick one design, bounce the other session);
     - Require running the test suites of **both** features after resolution, not just linter/build.
4. **Contract & Agent Mode Hardening (Review §2.3, §4.3, §4.4)**
   - *Gap 1 (`headless-executor-contract`)*: Needs two explicit rules currently only implied on the Architect side: (a) **one task, one commit** at task end scoped strictly to the task's files; (b) **isolation blast-radius**: never leave `working_directory` or touch sibling worktrees / main checkout. Also should include the exact Markdown skeleton of `Final Report` and require exact verification commands + output.
   - *Gap 2 (Executor skill authoring guide & Kilo agent mode)*: Census whether `skills_to_load` is actually used in `metrics.jsonl` / task records, decide whether to ship a dedicated `headless-executor` Kilo agent definition, and document how telemetry-derived project-local Executor skills should be structured.
5. **Rules vs. Incident Narratives — Progressive Disclosure (Review §1.4 & Tier 3)**
   - *Gap*: `orchestration-methodology` / `kilo-mcp-orchestrator` is ~317 lines because every live incident narrative is inline in `SKILL.md` (plus stack-specific mentions like JPA annotations / `.ts` files in Phase 5). Moving the full incident stories to `references/incidents.md` while keeping crisp 1–2 line imperative rules in `SKILL.template.md` will cut activation token cost significantly without losing hard-won operational rules.

### Track B — MCP Server & New Executor Bindings (`kilo-mcp`, `claude-mcp`, `pi`)

1. **Server-Side Task Completion Wait (`task-completion-notification-spec.md` Part 1)**
   - *Gap*: `kilo_implement(background=true)` returns immediately, forcing the orchestrator either to poll `kilo_task_progress`/`kilo_task_status` (burning orchestrator tokens) or use a shell PID watcher (which breaks if the launching process dies and needs log-file reconciliation).
   - *Solution*: Add `kilo_task_wait(task_id, timeout_seconds=None)` in `kilo-mcp/server.py` (with full crash/log-file reconciliation via `_reconcile_task_if_orphaned`) + unit tests in `test_server.py`.
2. **Decision Telemetry & ROI Analysis Rework (Review §2.4, §3.1, §3.4)**
   - *Gap*: `kilo_metrics` divides `delegation_cost_usd` by an uncalibrated heuristic `inline_estimate_usd` and never records when the Architect chooses the `inline` branch or discards a completed task at review.
   - *Solution*: Add `kilo_log_decision` (`delegate` | `inline` | `escalate` | `discarded`, reason, task ref, whether follow-up fix was needed), extend `kilo_metrics` to report observable rates (cost per completed task, rework/bounce rate, cancellation rate, discard rate, inline follow-up rate), update `delegation-roi-analysis` / `mcp-metrics-analyst`, and tighten the default `delegation_policy` in `kilo-mcp.example.toml`.
3. **Structured Verification Gate Tool (Review §3.2)**
   - *Gap*: Reading full diffs and verbose test outputs in Phase 5 is the largest context consumer for the Architect.
   - *Solution*: Add a verification gate tool (or mode on `kilo_run_command`) in `kilo-mcp/server.py` that runs project check commands in a worktree and returns a compact structured verdict (pass/fail per check + failing output only).
4. **`claude-mcp` Phase 1 Spike & Server Implementation (`claude-mcp/SPEC.md`)**
   - *Gap*: `claude-mcp` has a reviewed spec (round-001) identifying the trade-off between Option A (`claude --bg --session-id <uuid>`) and Option B (detached `claude -p --output-format json --session-id <uuid>` subprocess with PID control for `claude_task_cancel`). Needs the Phase 1 empirical spike followed by the minimal MCP server.
5. **Pi (`pi.dev`) Executor Binding Evaluation (`workspace T006`)**
   - *Gap*: Evaluate whether Pi's RPC/SDK supports headless background execution, file-scope constraints, and structured reports as a third Executor binding.

### Track C — Cross-Repo Consistency & Hygiene (`workspace T003, T004`)

1. **Docs consistency for Emergent Tasks (`workspace T003`)**: update `agentic-coding-kit/README.md` and `docs/` wherever `macroplan-authoring` is described so emergent tasks (`T###`) are mentioned alongside initiatives.
2. **Stale `mcp-orchestrator` name cleanup (`workspace T004`)**: scan `~/.kilo`, `~/.config/kilo`, and repo agent files for any remaining references to `mcp-orchestrator` (renamed to `kilo-mcp-orchestrator`).
