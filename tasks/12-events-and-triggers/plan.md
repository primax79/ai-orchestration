# 12 - Events, orchestration sessions and triggers

> **Derived from:** [`../specs/events-and-triggers.md`](../specs/events-and-triggers.md). Codex review of the spec comes first, before 12.1 is dispatched.

## Tasks (One Task = One Commit)

### 12.1 - Headless resumption facts (research, no code)

- **Status:** `open` · **Size:** S · **Executor:** self · **Repo:** `ai-orchestration/`
- **Goal:** Verify on the installed CLIs, for Claude (`-p --session-id` then `-p --resume`), Kilo (`run -s`) and Codex (`exec resume`):
  - that a session resumed headlessly keeps its full context across many turns;
  - what happens when two resumptions overlap (to justify the serialized queue);
  - how cost and usage are reported per turn;
  - how a turn is cancelled.

  Record the facts in spec §0.
- **Verification:** A live three-turn conversation per tool in a scratch repo, recorded as fixtures.

### 12.2 - Core: event log (`events.jsonl`, emission in every locked mutation, `events tail`)

- **Status:** `open` · **Size:** L · **Depends on:** 11.4 and 10.4 (`tasks_engine.py` lane), 07.12 (runs lane) · **Repo:** `ai-orchestration/`
- **Goal:** Spec §1, for `tasks_engine.py` (tasks, questions, inbox), `orchestration_runs.py` (runs) and `orchestration_config.py` (config).

### 12.3 - Core: session registry and the `questions apply` step

- **Status:** `open` · **Size:** M · **Depends on:** 12.2
- **Goal:** Spec §2 and §3, including the `origin-session` field.

### 12.4 - Core: trigger engine (`triggers run-once` and `triggers daemon`, rules, safety)

- **Status:** `open` · **Size:** L · **Depends on:** 12.3, 07.12
- **Goal:** Spec §5. The answer-and-resume rule replaces task 08.6.

### 12.5 - Core: headless orchestrator session (start, stop, pause, durable serialized turn queue, transcripts, event coalescing)

- **Status:** `open` · **Size:** L · **Depends on:** 12.1, 12.3, 07.12 · **Repo:** `ai-orchestration/` (runs lane)
- **Goal:** Spec §0, including role vs session, succession (automatic and manual rotation), the handoff prompt built from files, and `orchestrator.rotated` events.
- **Verification:**
  - Tests with stub agents:
    - a resumption failure triggers succession;
    - the new generation receives a handoff turn that contains the pending events and the open questions;
    - the queue continues after succession;
    - two concurrent enqueues never produce overlapping resumptions.

### 12.8 - UI: orchestrator chat panel (transcript, streaming reply, cancel, pause, queue view)

- **Status:** `open` · **Size:** L · **Depends on:** 12.5, 12.6 (frontend and backend lanes)
- **Goal:** Spec §0 "Owner chat in the UI".

### 12.6 - UI: event stream over WebSocket, notification area, Triggers page, session chips, "awaiting application" group

- **Status:** `open` · **Size:** L · **Depends on:** 12.4 (frontend and backend lanes)
- **Goal:** Spec §6.

### 12.7 - VS Code: event watcher and notifications

- **Status:** `open` · **Size:** S · **Depends on:** 12.6 (VS Code lane)
- **Goal:** Spec §1 "Reading" and §6, in the extension.
