# 12 - Events, orchestration sessions and triggers

> **Derived from:** [`../specs/events-and-triggers.md`](../specs/events-and-triggers.md). The §0, §0b and §0c amendments are normative. Plan rewritten on 2026-10-17 after the Codex review: 12.2 is split per file, and the lane dependencies are explicit.

## Tasks (One Task = One Commit)

### 12.1 - Headless resumption facts (merged into 07.5)

- **Status:** `delivered` (2026-10-18; claude; resumption facts recorded in tasks/12-events-and-triggers/notes/12.1-resumption-facts.md; engine fixes found there tracked as T022) · **Size:** M · **Executor:** self · **Depends on:** 07.12
- **Goal:** Task 07.5 (live capture with the real CLIs) also covers spec §0 and E8:
  - resume from a fresh process, after a crash, after a cancel, with an invalid session id, with two overlapping resumes, and after a cwd change;
  - normalized usage fields.

  Kilo runs with disposable writable XDG state directories. The fixtures go to `scripts/fixtures/runs/`.

### 12.11 - Core: event store (outbox, counter, chunk manifest, reconciliation, `events tail`)

- **Status:** `done` (2026-10-18; claude; merged) · **Size:** L · **Depends on:** 10.4 (`tasks_engine.py` lane end) · **Repo:** `ai-orchestration/` (new module `scripts/orchestration_events.py`)
- **Goal:** E1, E13 and §1 reading.

### 12.12 - Emit events from `tasks_engine.py`

- **Status:** `in progress` (2026-10-18; claude; kilo, worktree task/12.12-engine-events) · **Size:** M · **Depends on:** 12.11
- **Goal:** Events for tasks, questions and the inbox, through the outbox; the E11 application ledger with `questions apply`.

### 12.13 - Emit events from `orchestration_runs.py` and extract the supervised-invocation primitive

- **Status:** `open` · **Size:** L · **Depends on:** 12.11, 07.11 (runs lane end)
- **Goal:** E1 and E4.
- **Also (from the 12.11 review):** `events tail --session S` (spec §1 line 128) was not implemented in 12.11; add it here, where events start carrying the session.

### 12.14 - Emit events from `orchestration_config.py`; config writes under a lock

- **Status:** `done` (2026-10-18; claude; merged) · **Size:** S · **Depends on:** 12.11
- **Goal:** E1 and E10 `config.changed`.

### 12.3 - Session registry and identifiers

- **Status:** `open` · **Size:** M · **Depends on:** 12.12, 12.13
- **Goal:** §2 and E10, including the header amendments in specs 08 and 09.

### 12.4 - Trigger engine

- **Status:** `open` · **Size:** L · **Depends on:** 12.3
- **Goal:** §5, E7, and the reduced-capability policy for unattended turns (E3).

### 12.5 - Headless orchestrator role (sessions, queue, turns, succession, bounds)

- **Status:** `open` · **Size:** L · **Depends on:** 12.1, 12.3, 12.13
- **Goal:** §0, E2, E4, E5, E6, E8 and E9.

### 12.9 - Orchestrator configuration: reassignment as succession, `ai-orch setup` engine shared with the `orchestration-setup` skill

- **Status:** `open` · **Size:** M · **Depends on:** 12.5
- **Goal:** §0b, core part.

### 12.6 - UI: event and queue streams, notification area, Triggers page, session chips, "awaiting application" group

- **Status:** `open` · **Size:** L · **Depends on:** 12.4, frontend lane after 10.5
- **Goal:** §6 and E12.

### 12.8 - UI: orchestrator chat panel

- **Status:** `open` · **Size:** L · **Depends on:** 12.5, 12.6
- **Goal:** §0 "Owner chat in the UI" and E12; proposed-action confirmations (E3).

### 12.10 - UI: Orchestrator card in Config (current holder, Reassign…, pause/rotate) and first-run setup wizard

- **Status:** `open` · **Size:** M · **Depends on:** 12.9, 12.8
- **Goal:** §0b, UI part.

### 12.7 - VS Code: event watcher and notifications

- **Status:** `open` · **Size:** S · **Depends on:** 12.6, VS Code lane after 10.3
- **Goal:** §1 "Reading" (E13) and §6.

> 2026-10-17: tasks `12.2a`–`12.2d` renumbered `12.11`–`12.14` (letter-suffixed ids are not task ids; validate flagged them and their dependencies were invisible).
