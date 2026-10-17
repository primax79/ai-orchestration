# 10 - Abstract timeline: dependencies and priorities

> **Derived from:** [`../specs/timeline-gantt.md`](../specs/timeline-gantt.md). Lane order: see `../06-control-plane-safety/plan.md`.

## Tasks (One Task = One Commit)

### 10.1 - Engine: `tasks graph` (columns, ready queue, longest chain, Mermaid), `tasks set-priority`, `tasks set-deps`, cycle check

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 09.1 (same file, `tasks_engine.py` lane) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`
- **Goal:** Spec §2.
- **Verification:**
  - Tests:
    - every form of the `NN.T` bullets is parsed, with inherited priorities;
    - columns and the ready queue are computed correctly;
    - `set-deps` refuses a cycle and names it;
    - `set-deps` keeps the free text of a `**Depends on:**` bullet;
    - `set-priority` works on `T###` (header) and on `NN.T` (bullet created or updated);
    - a stale hash is refused;
    - `--dry-run` writes nothing.
  - Live: `tasks graph --json` on this repo shows 06–10 in coherent columns, and `--mermaid` renders in VS Code.

### 10.2 - UI: graph and edit endpoints and the Timeline tab (arrows, ready queue, priority and dependency editing)

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 10.1, 06.8 (frontend lane; can run before 08.4 when 08.3 is late) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`, `frontend/src/**`
- **Goal:** Spec §3. Endpoints: `GET /api/tasks/graph`, and `POST /api/tasks/{id}/priority` and `/deps`, each with a `/preview` variant.
- **Verification:** Live with the Playwright MCP on a scratch copy of this repo's `tasks/`:
  - the columns and arrows are visible;
  - changing a priority reorders the column and the ready queue;
  - adding a dependency moves the card one column to the right;
  - a cycle is refused in the picker;
  - removing an arrow works;
  - a screenshot is attached to the Final Report.

### 10.3 - VS Code: Timeline in the webview

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 10.2, 06.9 (VS Code lane) · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/cli-client.ts`, `dist-webview/**`
- **Goal:** Spec §3 "VS Code".
- **Verification:** Live in an Extension Development Host.
