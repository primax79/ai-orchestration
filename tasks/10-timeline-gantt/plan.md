# 10 - Timeline (Gantt) view with dependencies

> **Derived from:** [`../specs/timeline-gantt.md`](../specs/timeline-gantt.md). Lane order: see `../06-control-plane-safety/plan.md`.

## Tasks (One Task = One Commit)

### 10.1 - Engine: `ai-orch tasks graph`, plan parsing of Status/Depends on/Estimate/Lane, cycle check

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 09.1 (same file, `tasks_engine.py` lane) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`
- **Goal:** Spec §2.
- **Also:**
  - add `**Estimate:**` and `**Lane:**` bullets to the open tasks of the plans 06–10 (one commit with the code);
  - regenerate `../gantt.md` from `tasks graph` (Mermaid output: `tasks graph --mermaid`), so the hand-written snapshot disappears.
- **Verification:**
  - Tests: parsing of each bullet form; done dates; schedule after dependencies; lane serialization; critical path; a cycle is an error; an unknown dependency is a warning.
  - Live: `tasks graph --json` on this repo lists every 06–10 task with its edges, and `--mermaid` renders in VS Code.

### 10.2 - UI: backend endpoint and Timeline tab with dependency arrows

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 10.1, 06.8 (frontend lane; can run before 08.4 when 08.3 is late) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`, `frontend/src/**`
- **Goal:** Spec §3: the `GET /api/tasks/graph` endpoint and the Timeline tab.
- **Verification:** Live with the Playwright MCP on this repo's `tasks/`:
  - the tab shows the 06–10 bars and the arrows;
  - "hide done" works;
  - a click opens the task;
  - a screenshot is attached to the Final Report.

### 10.3 - VS Code: Timeline in the webview

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 10.2, 06.9 (VS Code lane) · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/cli-client.ts`, `dist-webview/**`
- **Goal:** Spec §3 "VS Code".
- **Verification:** Live in an Extension Development Host.
