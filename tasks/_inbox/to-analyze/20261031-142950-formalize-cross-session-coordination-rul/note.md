# N089 Formalize cross-session coordination rules (registry, durable handoff, one owner, delegator closes, session limits, broadcast validity)

- id: N089
- title: Formalize cross-session coordination rules (registry, durable handoff, one owner, delegator closes, session limits, broadcast validity)
- kind: request
- status: ready
- created: 2026-10-31T14:29:50.465139+00:00
- author: gcube-audit-0b (gcube_audit coordinator, Claude)
- about: N088, task-pipeline, orchestration-workflow, initiative 16, initiative 19
- produced: -
- processed-by: -
- short: Coordination rules

Owner request (2026-10-31, gcube_audit session): the coordination rules below must be formalized in ai-orchestration
(conventions, task-pipeline skill, orchestrator/broker design), not only written to each project. They come from a
cross-session review of 2026-10-31 that covered about 86 Claude sessions (Mac and hub) and 524 Kilo root sessions since
2026-10-21. Complements N088 (robust cross-workspace communication), which covers the transport; this note covers the
working rules.

## What the review found (counts, 2026-10-21..31)

- About 70 pending items in the gCube projects alone: 21 owner questions never answered, 18 cross-session requests
  dropped, 14 promised and not done, 8 decisions that exist only in transcripts.
- Projects with no task registry (d4science_kb, gcube_atlas, dave_agent, EOSC): their pending work lives only in
  transcripts.
- Kilo: 46 of 482 Mac root sessions ended mid-run. 29 Kilo worktrees are left behind, 15 of them with unmerged commits
  (11 with no remote ref). kilo-mcp has 3 tasks stuck `running` with dead pids and a stale `queue-runner.lock`. Delivered
  subtasks were never verified.
- The same artefact is edited by several projects: the Ansible Keycloak client definitions in 3 separate PRs, and
  ai-orchestration itself in two writable copies on the hub.
- 4 sessions hit the 5-hour limit at the same time (2026-10-31 13:36) with agents or Kilo runs in flight.
- A broadcast ("stay blocked") stayed active about an hour after its blocker had closed.

## Rules to formalize (proposed)

1. **Every project has a task registry** (`tasks/00-INDEX.md` per task-pipeline). Any request, decision or delegation
   that appears in a session becomes a task or an inbox note in the owning project before the turn ends. Decisions only
   in a transcript do not count.
2. **Durable handoff.** Anything that must survive goes as a committed note in the receiver's inbox (canonical copy,
   hub or Mac per the registry). A cross-session message only points to it. The receiver acknowledges by moving the note
   to `_inbox/integrated/` with the task id; an unacknowledged note is visible to the sender (sweep or broker).
3. **One owner per shared artefact.** Shared repositories or files edited from several projects (e.g. Ansible Keycloak
   client definitions) have one owning project. The others send requests. One writable copy per repository on the hub.
4. **The delegator closes the delegation.** A delegated run (subagent, Kilo, headless Claude) is closed only when its
   result is read and integrated or dropped and its worktree/branch is merged, pushed or deleted. A periodic sweep lists
   leftovers: unmerged worktrees, uncollected runs, stuck `running` tasks.
5. **Session limits are a planning input.** Check the remaining budget before long delegations. A session close to its
   limit writes its in-flight state (task Progress) first, so another session can resume.
6. **Broadcasts carry a validity condition** (e.g. "until T048 closes") and are re-checked before they are repeated.
   This matches the release condition of N088 R2.

## Where it could live

- task-pipeline skill and tasks/AGENTS.md convention: rules 1, 2 (ack by move to `integrated/`), 4.
- orchestration-workflow skill / AGENTS.md pattern (doc 04): rules 3, 5, 6.
- broker / initiative 16 and 19, N088: a sweep command for rules 2 and 4 (unacknowledged notes, leftover worktrees,
  stuck runs). The extractor scripts of the review exist (session transcripts, Kilo session DB, worktree state) and can
  be contributed as a starting point if wanted.

---
- Author: gcube-audit-0b (gcube_audit coordinator, Claude)
- Workspace: /Users/Alfredo/works/gcube_audit
- ai-orch: 1.1.0 (2965604)
- Date: 2026-10-31 14:29:50 UTC
