# 10 - Abstract timeline: dependencies and priorities

> **Derived from:** [`../specs/timeline-gantt.md`](../specs/timeline-gantt.md). Lane order: see `../06-control-plane-safety/plan.md`.

## Tasks (One Task = One Commit)

### 10.1 - Engine: `tasks graph` (columns, ready queue, heaviest chain, Mermaid), `size` field, `tasks set-priority`, `tasks set-size`, `tasks set-deps`, cycle check

- **Status:** `done` (2026-10-18; claude; merged) · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1 (child parser; same file, `tasks_engine.py` lane) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md` (the `size` extension field)
- **Goal:** Spec §2. Also add `**Size:**` to the open tasks of the plans 06–10, using these estimates: 06.8 L, 06.9 M, 07.4 L, 07.5 M, 07.6 M, 07.7 L, 07.8 M, 07.9 S, 07.10 S, 08.3 S, 08.4 M, 08.5 S, 08.6 S, 09.1 M, 09.2 M, 09.3 L, 09.4 M, 09.5 M, 09.6 S, 10.1 M, 10.2 L, 10.3 S.
- **Verification:**
  - Tests:
    - every form of the `NN.T` bullets is parsed, with inherited priorities;
    - columns and the ready queue are computed correctly;
    - `set-deps` refuses a cycle and names it;
    - `set-deps` keeps the free text of a `**Depends on:**` bullet;
    - `set-priority` and `set-size` work on `T###` (header) and on `NN.T` (bullet created or updated);
    - the heaviest chain and the totals follow the sizes;
    - a stale hash is refused;
    - `--dry-run` writes nothing.
  - Live: `tasks graph --json` on this repo shows 06–10 in coherent columns, and `--mermaid` renders in VS Code.

### 10.2 - UI: graph and edit endpoints and the Timeline tab (arrows, ready queue, priority and dependency editing)

- **Status:** `in progress` (2026-10-18; claude; kilo, ai-orchestration-ui worktree task/10.2-timeline) · **Size:** L · **Profile:** `bulk-execution` · **Depends on:** 10.1, 06.8 (frontend lane; can run before 08.4 when 08.3 is late) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`, `frontend/src/**`
- **Goal:** Spec §3. Endpoints: `GET /api/tasks/graph`, and `POST /api/tasks/{id}/priority`, `/size` and `/deps`, each with a `/preview` variant.
- **Verification:** Live with the Playwright MCP on a scratch copy of this repo's `tasks/`:
  - the columns and arrows are visible;
  - changing a priority reorders the column and the ready queue;
  - changing a size changes the card width and the totals;
  - adding a dependency moves the card one column to the right;
  - a cycle is refused in the picker;
  - removing an arrow works;
  - a screenshot is attached to the Final Report.

### 10.3 - VS Code: Timeline in the webview

- **Status:** `open` · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 10.2, 06.9 (VS Code lane) · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/cli-client.ts`, `dist-webview/**`
- **Goal:** Spec §3 "VS Code".
- **Verification:** Live in an Extension Development Host.

### 10.4 - Engine: microtasks (`micro` category, reduced schema, `tasks micro`, `tasks promote`, XS size), kind and labels

- **Status:** `in progress` (2026-10-18; claude; kilo, worktree task/10.4-microtasks) · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 10.1 (same file) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md`, `plugins/architect-side/skills/task-pipeline/SKILL.md` (document the microtask form)
- **Goal:** Spec §5 (everything except batch runs and UI) and spec §6 engine part:
  - `kind` and `labels` fields (`T###` header extensions, `NN.T` bullets);
  - `set-kind` and `set-labels`;
  - `--kind`/`--label` filters;
  - `tasks labels`;
  - validation.
- **Verification:**
  - Tests: label format and kind set are validated; `set-labels --add/--remove` round-trips; filters combine with AND across fields and OR within one field; a microtask validates with the reduced header and `## What` only; it appears in `tasks graph` with size `XS`; `promote` produces a full task that validates and keeps its id and the dependencies that point to it; `tasks micro` allocates ids concurrently without clashes.

### 10.5 - UI: microtask quick-add, XS pills, "Promote", kind and labels, shared filter bar

- **Status:** `open` · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 10.4, 10.2 (frontend lane) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `frontend/src/**`
- **Goal:** Spec §5 "Creation" (UI) and the timeline pill, plus spec §6 UI: kind icons, label chips, the shared filter bar, the label editor with autocomplete, group by label. Also: in the inbox tab (09.3), "Convert to microtask" for `bug` notes, when 09.3 has landed.
- **Verification:** Live with Playwright: quick-add a bug microtask → it appears as an XS pill in the ready queue → Promote → it becomes a full card.

### 10.6 - Backlog views: compact "Next up", separate view switcher (Queue, Kanban, Tree, Timeline)

- **Status:** `delivered` (2026-10-17; merged and checked live with Playwright: Queue/Kanban/Tree views, Done hidden, Delivered+Verified column, Tree state filter, Waiting-first Kanban) · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 06.8 (frontend lane; can run before 10.1 and enhance once 10.1 and 11.3 land) · **Repo:** `ai-orchestration-ui/`
- **Origin:** owner feedback (2026-10-17). "Next Up Focus" was unclear and huge: it listed every `NN.T`, because initiative tasks inherited the initiative state, and it sat on the same page as the Kanban.
- **Goal:**
  - The Backlog tab gets a view switcher: **Queue**, **Kanban**, **Tree** (11.3), **Timeline** (10.2). The last chosen view is remembered (localStorage).
  - **Queue** = "what to start next": at most 5 compact rows with id, title, priority, size and kind, plus a one-line explanation ("tasks marked next-up, or the first ready tasks by priority once the timeline engine lands"). There are no cards.
  - The KPI counters become a single compact strip.
  - **Kanban (owner feedback, 2026-10-17):**
    - the Done column is hidden by default, with a toggle button ("Show done") whose state is remembered;
    - Delivered and Verified share one column: Delivered cards on top, Verified cards below, with a thin divider and a sub-heading for each;
    - same for the column-toggle of Dropped, if present.
  - Until 10.1 lands, Queue uses `next-up: yes` emergent tasks only, never `NN.T`; after 10.1 it uses the `ready_queue`.
- **Verification:** Live with Playwright on this repo's `tasks/`: the Queue view shows at most 5 rows; switching views keeps the filters; at 1000 px every view fits without horizontal scroll.
