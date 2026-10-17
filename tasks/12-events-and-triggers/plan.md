# 12 - Events, orchestration sessions and triggers

> **Derived from:** [`../specs/events-and-triggers.md`](../specs/events-and-triggers.md). Codex review of the spec comes first, before 12.1 is dispatched.

## Tasks (One Task = One Commit)

### 12.1 - Claude Code delivery check (research, no code)

- **Status:** `open` · **Size:** S · **Executor:** self · **Repo:** `ai-orchestration/`
- **Goal:** Verify against Claude Code's documentation and the installed CLI which hook events can add context to the next turn, and how a hook command receives the session id. Record the facts and the chosen mechanism in the spec §4.
- **Verification:** A cited source for every claim. A throwaway hook in a scratch project injects a test line that a real session sees.

### 12.2 - Core: event log (`events.jsonl`, emission in every locked mutation, `events tail`)

- **Status:** `open` · **Size:** L · **Depends on:** 11.4 and 10.4 (`tasks_engine.py` lane), 07.12 (runs lane) · **Repo:** `ai-orchestration/`
- **Goal:** Spec §1, for `tasks_engine.py` (tasks, questions, inbox), `orchestration_runs.py` (runs) and `orchestration_config.py` (config).

### 12.3 - Core: session registry and the `questions apply` step

- **Status:** `open` · **Size:** M · **Depends on:** 12.2
- **Goal:** Spec §2 and §3, including the `origin-session` field.

### 12.4 - Core: trigger engine (`triggers run-once` and `triggers daemon`, rules, safety)

- **Status:** `open` · **Size:** L · **Depends on:** 12.3, 07.12
- **Goal:** Spec §5. The answer-and-resume rule replaces task 08.6.

### 12.5 - Delivery to sessions: Claude Code hook and monitor recipe; Kilo and Codex skill guidance

- **Status:** `open` · **Size:** M · **Depends on:** 12.1, 12.3
- **Goal:** Spec §4. Lives in the binding repos (`kilo-mcp` skills) and in a Claude Code hook script under `ai-orchestration/hooks/`.

### 12.6 - UI: event stream over WebSocket, notification area, Triggers page, session chips, "awaiting application" group

- **Status:** `open` · **Size:** L · **Depends on:** 12.4 (frontend and backend lanes)
- **Goal:** Spec §6.

### 12.7 - VS Code: event watcher and notifications

- **Status:** `open` · **Size:** S · **Depends on:** 12.6 (VS Code lane)
- **Goal:** Spec §1 "Reading" and §6, in the extension.
