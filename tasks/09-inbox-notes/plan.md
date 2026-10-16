# 09 - Inbox: draft notes, reports and screenshots, processed into tasks

> **Derived from:** [`../specs/inbox-notes.md`](../specs/inbox-notes.md). Read the spec first. Lane order: see `../06-control-plane-safety/plan.md` ("UI lane order"); 09 tasks join the same lanes.

## Tasks (One Task = One Commit)

### 09.1 - Engine: note folders, `ai-orch inbox ...`, `tasks new --from-note`

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 06.10 (lock); runs in the `tasks_engine.py` lane after 06.10, before or after 08.1 (never in parallel with it) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `plugins/architect-side/skills/task-pipeline/SKILL.md` (document the note folder form under "Capture")
- **Goal:** Spec §2 and §3.
- **Verification:**
  - Tests:
    - add / edit / attach (a png accepted; a png-named text file refused by the magic-byte check; a file over 10 MB refused) / detach / resolve / discard / reopen round-trips;
    - id uniqueness under concurrency;
    - legacy plain `.md` notes are listed;
    - `tasks new --from-note` produces a task that `tasks validate` accepts, with `sources` pointing to the note.

### 09.2 - UI backend: inbox endpoints with authenticated uploads

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 09.1, 06.7 (backend lane) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Spec §5 "Safety", plus thin endpoints over `ai-orch inbox`: list / show / add / edit / attach (multipart, streamed to a temp file, then `inbox attach`) / detach / resolve / discard / reopen / serve attachment.
- **Verification:**
  - Tests: an upload without the token → 401; an oversized upload is refused before it is fully read; a traversal name is refused; a served attachment has the sniffed type and `nosniff`.

### 09.3 - Frontend: Inbox tab, editor with paste and drag-drop images, manual "Convert to task"

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 09.2, 06.8 (frontend lane) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Spec §5, except "Process with…".
- **Verification:**
  - Live with the Playwright MCP on a scratch workspace:
    - create a note;
    - paste an image (simulated clipboard `paste` event with a png blob) → thumbnail appears and `attachments/01-*.png` exists on disk;
    - mark it Ready;
    - Convert to task → `T###` file created and valid;
    - Mark processed → the folder is in `analyzed/` with `produced` set.

### 09.4 - Agent triage: `triage` run mode, proposal review, accept

- **Status:** `open` · **Profile:** `deep-reasoning` · **Depends on:** 09.1, 07.4, 07.10 (questions) · **Repo:** `ai-orchestration/` (+ UI in 09.5)
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:** Spec §4 "By an agent":
  - the `triage` mode, with its prompt and per-tool image passing;
  - a read-only permission policy;
  - parsing of the `ai-orch-triage` block into a stored proposal;
  - `run accept-triage RUN_ID [--only ids] --expect-note-hash H`, which creates the tasks and resolves the note.
- **Verification:**
  - Tests with the stub agent.
  - Live with one real tool on a note with a screenshot: the proposal references what is visible in the image.

### 09.5 - Frontend: "Process with…" and proposal review

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 09.3, 09.4, 07.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `backend/server.py` (accept endpoint), `frontend/dist/**`
- **Goal:** Spec §4 review flow in the UI.
- **Verification:** Live: process a note with the stub agent, edit one proposed task, reject another, accept → only the accepted one exists.

### 09.6 - VS Code: inbox tab parity (paste and upload through postMessage)

- **Status:** `open` · **Profile:** `bulk-execution` · **Depends on:** 09.3, 06.9 (VS Code lane) · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/cli-client.ts`, `dist-webview/**`
- **Goal:** Spec §5 "VS Code".
- **Verification:** Live in an Extension Development Host: paste a screenshot into a note; the file appears in `attachments/`.
