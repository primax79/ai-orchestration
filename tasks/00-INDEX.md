# Task Index — ai-orchestration

Live registry of planned initiatives and emergent tasks for `ai-orchestration`. Convention: [`AGENTS.md`](AGENTS.md). Shared context: [`CONTEXT.md`](CONTEXT.md).

## Initiatives

`#` is the stable id (folder/task prefix); `Priority` is execution order. Each task (`NN.T`) is sized for one independently-verifiable commit and ready for delegation.

| Priority | # | Initiative | Status | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | 01 | [Consolidate Orchestration & Task Skills into `ai-orchestration`](done/01-repo-consolidation/plan.md) | done | - | M |
| 2 | 02 | [Formal Task Model, State Machine & `orchestration.toml` Specification](done/02-task-and-config-spec/plan.md) | done | 01 | M |
| 3 | 03 | [Configuration & Task Management Skill + Python Scripts (`orchestration_config.py`, `tasks_engine.py`)](done/03-skill-and-script-engine/plan.md) | done | 02 | M |
| 4 | 04 | [Orchestration Methodology & Skill Refinements (Review Tier 2)](04-methodology-refinements/plan.md) | partial (`T003`–`T005` done; `T006` open) | 01 | M |
| 5 | 05 | [Standalone CLI (`ai-orch`), From-Scratch Installer & Extension Control Plane](done/05-cli-and-ui-handoff/plan.md) | done | 02, 03 | L |
| 6 | 06 | [Control-plane safety (Doctor, index, UI backend, VS Code bridge)](06-control-plane-safety/plan.md) | in progress (done: 06.1–06.8, 06.10; 06.9 delivered, live VS Code check pending) | 05 | L |
| 7 | 07 | [Agent runs from the control plane (choose who does the work)](07-agent-runs-from-ui/plan.md) | in progress (done: 07.1–07.4, 07.6, 07.7, 07.10; next: 07.8, 11.2) | 05, 06 | L |
| 8 | 08 | [Blocking questions (format, engine, pending-answers UI)](08-blocking-questions/plan.md) | in progress (done: 08.1–08.4; 08.5 delivered, live VS Code check pending; next: 08.6) | 06 | M |
| 9 | 09 | [Inbox: draft notes, reports and screenshots, processed into tasks](09-inbox-notes/plan.md) | in progress (done: 09.1, 09.2; next: 09.3) | 06 (07 for agent triage) | M |
| 10 | 10 | [Abstract timeline: dependencies and priorities](10-timeline-gantt/plan.md) | open | 06, 09.1 | S |
| 11 | 11 | [First-class task hierarchy (N levels)](11-subtasks/plan.md) | open | 06, 09.1 | M |
| 12 | 12 | [Events, orchestration sessions and triggers](12-events-and-triggers/plan.md) | open (spec in review) | 07, 08, 11 | L |
| 13 | 13 | [Doctor rework: findings that are true, actionable and resolvable](13-doctor-rework/plan.md) | open | 06 | M |

## Specs

| Spec | Drives |
| --- | --- |
| [orchestration-config-and-agents-md](specs/orchestration-config-and-agents-md.md) | 02, 03 |
| [task-and-state-model](specs/task-and-state-model.md) | 02, 03, 05 |
| [orchestration-extension-spec](specs/orchestration-extension-spec.md) | 05 |
| [control-plane-safety](specs/control-plane-safety.md) | 06 |
| [agent-runs-from-ui](specs/agent-runs-from-ui.md) | 07 |
| [blocking-questions](specs/blocking-questions.md) | 08 |
| [inbox-notes](specs/inbox-notes.md) | 09 |
| [timeline-gantt](specs/timeline-gantt.md) | 10 |
| [subtasks](specs/subtasks.md) | 11 (and 10.1 builds on 11.1) |
| [events-and-triggers](specs/events-and-triggers.md) | 12 (supersedes 08.6) |

## Next up

<!-- ai-orch:generated next-up -->
| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
| T008 | P1 | [claude-mcp Phase 1 empirical spike (Option A --bg vs Option B detached -p)](server-and-bindings/T008-claude-mcp-phase1-spike.md) | claude | `Read tasks/server-and-bindings/T008-claude-mcp-phase1-spike.md and ../claude-mcp/SPEC.md, run the Phase 1 spike, record findings, and update the task and the registry.` |
| T007 | P2 | [Structured verification gate tool in kilo-mcp](server-and-bindings/T007-verification-gate-tool.md) | kilo | `Read tasks/server-and-bindings/T007-verification-gate-tool.md, do the open steps, run the Verification, update the task and the registry.` |
| T016 | P1 | [Study: are the Doctor's persistent findings real, and do we handle them right?](env-doctor/T016-doctor-findings-study.md) | claude | `Read tasks/env-doctor/T016-doctor-findings-study.md and produce the report in tasks/env-doctor/notes/.` |
<!-- /ai-orch:generated next-up -->

## Tasks by category

<!-- ai-orch:generated tasks-by-category -->
### methodology

Evolutions and refinements to the orchestration skills (`orchestration-methodology`, `conflict-resolver`, `headless-executor-contract`). Owner session: unassigned ([README](methodology/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T006 | P3 | [Extract incident narratives to references/incidents.md (progressive disclosure)](methodology/T006-incidents-progressive-disclosure.md) | open | self | T003 |

### server-and-bindings

Standalone MCP server evolutions (`../kilo-mcp/`, `../claude-mcp/`). Owner session: unassigned ([README](server-and-bindings/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T008 | P1 | [claude-mcp Phase 1 empirical spike (Option A --bg vs Option B detached -p)](server-and-bindings/T008-claude-mcp-phase1-spike.md) | open | claude | - |
| T007 | P2 | [Structured verification gate tool in kilo-mcp](server-and-bindings/T007-verification-gate-tool.md) | in progress | kilo | - |
| T012 | P2 | [kilo-mcp: detect kilo run processes that hang after finishing](server-and-bindings/T012-kilo-run-hangs-after-completion.md) | verified | kilo | - |

### micro

Tasks in `micro`. Owner session: unassigned ([README](micro/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T015 | P3 | [Navbar labels wrap on narrow widths](micro/T015-navbar-narrow-width.md) | open | kilo | - |

### env-doctor

Tasks in `env-doctor`. Owner session: unassigned ([README](env-doctor/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T016 | P1 | [Study: are the Doctor's persistent findings real, and do we handle them right?](env-doctor/T016-doctor-findings-study.md) | delivered | claude | - |
| T017 | P2 | [Apply Q002: remove the untracked project-scope skill copies in ai-orchestration](env-doctor/T017-apply-q002-remove-the-untracked-project-scope-skil.md) | open | claude | - |
| T018 | P2 | [Q003 follow-up: precedence when orchestration-workflow and the generic orchestration skill coexist](env-doctor/T018-q003-follow-up-precedence-when-orchestration-workf.md) | open | claude | - |
| T019 | P3 | [Apply Q005: per-skill diff of the gcube-jenkins, gcube-security-audit and frontend-design copies](env-doctor/T019-apply-q005-per-skill-diff-of-the-gcube-jenkins-gcu.md) | open | claude | - |
<!-- /ai-orch:generated tasks-by-category -->

## Decisions waiting

<!-- ai-orch:generated decisions -->
| Key | Question | Blocks | Decider | Recommended |
| --- | --- | --- | --- | --- |
| - | None. | - | - | - |
<!-- /ai-orch:generated decisions -->

## Done

<!-- ai-orch:generated done -->
| Id | Task | Result | Closed |
| --- | --- | --- | --- |
| T010 | [Core skill renames decision (docs/06 taxonomy vs. current skill names)](done/methodology/T010-core-skill-naming-decision.md) | done | 2026-10-15 |
| T009 | [Product & per-skill usability, quickstart playbook, and instruction clarity](done/methodology/T009-usability-and-complete-documentation.md) | done | 2026-10-15 |
| T005 | [Hardening headless-executor-contract and evaluating Kilo agent mode](done/methodology/T005-headless-contract-and-agent-mode.md) | done | 2026-10-15 |
| T004 | [Rework conflict-resolver for Architect audience and incompatible designs](done/methodology/T004-conflict-resolver-rework.md) | done | 2026-10-15 |
| T003 | [Phase 5 explicit decision point and worktree lifecycle closure](done/methodology/T003-phase5-decision-and-worktree-cleanup.md) | done | 2026-10-15 |
| T002 | [Decision telemetry (kilo_log_decision) and ROI analysis rework](done/server-and-bindings/T002-decision-telemetry-and-roi-rework.md) | done | 2026-10-15 |
| T001 | [Task completion wait (kilo_task_wait) and watcher guidance](done/server-and-bindings/T001-task-completion-wait-and-watcher.md) | done | 2026-10-15 |
| T011 | [render-agents-md: render rules that match the actual orchestrator/executor topology](done/methodology/T011-render-agents-md-topology.md) | done | 2026-10-17 |
| T013 | [Answer confirmation dialog says "No modifications required"](done/micro/T013-answer-dialog-wording.md) | done | 2026-10-17 |
| T014 | [One backend test failed once in eleven runs](done/micro/T014-flaky-backend-test.md) | done | 2026-10-17 |
<!-- /ai-orch:generated done -->

## Dependency graph

```mermaid
flowchart TB
    I01["01: Repo Rename & Skill Consolidation (done)"]
    I02["02: Formal Task & Config Spec (done)"]
    I03["03: Skill + Python Scripts: orchestration_config.py & tasks_engine.py (done)"]
    I04["04: Methodology Refinements (T003-T005 done, T006 open)"]
    I05["05: CLI & UI Control Plane (done)"]
    I06["06: Control-plane safety (open)"]
    I07["07: Agent runs from the control plane (open)"]
    I08["08: Blocking questions (open)"]
    I09["09: Inbox notes and screenshots to tasks (open)"]
    I10["10: Abstract timeline, dependencies and priorities (open)"]
    I11["11: Task hierarchy, N levels (open)"]
    I12["12: Events, sessions, triggers (open)"]
    MCP["T001, T002 (done) / T007, T008 (open): Standalone MCP Servers (kilo-mcp & claude-mcp)"]

    I01 --> I02 --> I03 --> I05 --> I06
    I06 --> I07
    I06 --> I08
    I06 --> I09
    I06 --> I10
    I06 --> I11
    I11 --> I10
    I07 --> I12
    I08 --> I12
    I07 -.->|agent triage| I09
    I08 -.->|answer and resume| I07
    I01 --> I04
```
