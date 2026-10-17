# 09 - Inbox: draft notes, reports and screenshots, processed into tasks

> **Derived from:** [`../specs/inbox-notes.md`](../specs/inbox-notes.md). Read the spec first. Lane order: see `../06-control-plane-safety/plan.md` ("UI lane order"); 09 tasks join the same lanes.

## Tasks (One Task = One Commit)

### 09.1 - Engine: note folders, `ai-orch inbox ...`, `tasks new --from-note`

- **Status:** `done` (2026-10-17) · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 06.10 (lock); runs in the `tasks_engine.py` lane after 06.10, before or after 08.1 (never in parallel with it) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `plugins/architect-side/skills/task-pipeline/SKILL.md` (document the note folder form under "Capture")
- **Goal:** Spec §2 and §3.
- **Verification:**
  - Tests:
    - add / edit / attach (a png accepted; a png-named text file refused by the magic-byte check; a file over 10 MB refused) / detach / resolve / discard / reopen round-trips;
    - id uniqueness under concurrency;
    - legacy plain `.md` notes are listed;
    - `tasks new --from-note` produces a task that `tasks validate` accepts, with `sources` pointing to the note.

### 09.2 - UI backend: inbox endpoints with authenticated uploads

- **Status:** `done` (2026-10-17) · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 09.1, 06.7 (backend lane) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Spec §5 "Safety", plus thin endpoints over `ai-orch inbox`: list / show / add / edit / attach (multipart, streamed to a temp file, then `inbox attach`) / detach / resolve / discard / reopen / serve attachment.
- **Verification:**
  - Tests: an upload without the token → 401; an oversized upload is refused before it is fully read; a traversal name is refused; a served attachment has the sniffed type and `nosniff`.

### 09.3 - Frontend: Inbox tab, editor with paste and drag-drop images, manual "Convert to task"

- **Status:** `done` (2026-10-18; claude; verified and merged; T012 active since the kilo-mcp server restart) · **Size:** L · **Profile:** `bulk-execution` · **Depends on:** 09.2, 06.8 (frontend lane) · **Repo:** `ai-orchestration-ui/`
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

- **Status:** `delivered` (2026-10-17; claude; merged (6be6be2): triage mode read-only (claude Read/Glob/Grep/git read; codex sandbox read-only), proposal parsing, accept-triage; kilo argv gets '--' (fix: -f is an array option); live check with a real tool pending) · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 09.1, 07.4, 07.10 (questions) · **Repo:** `ai-orchestration/` (+ UI in 09.5)
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

- **Status:** `delivered` (2026-10-17; claude; merged (rebased, test conflict resolved keeping both); note ids validated, proposal path from RUN_ID_RE only; live run with a real tool pending) · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 09.3, 09.4, 07.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `backend/server.py` (accept endpoint), `frontend/dist/**`
- **Goal:** Spec §4 review flow in the UI.
- **Verification:** Live: process a note with the stub agent, edit one proposed task, reject another, accept → only the accepted one exists.

### 09.6 - VS Code: inbox tab parity (paste and upload through postMessage)

- **Status:** `delivered` (2026-10-17; claude; merged in vscode 0.3.0; owner live check in VS Code pending) · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 09.3, 06.9 (VS Code lane) · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/cli-client.ts`, `dist-webview/**`
- **Goal:** Spec §5 "VS Code".
- **Verification:** Live in an Extension Development Host: paste a screenshot into a note; the file appears in `attachments/`.

### 09.7 - Engine: general attachments (text, PDF), `feature` kind, task attachments, convert copies attachments

- **Status:** `done` (2026-10-17; claude; merged) · **Profile:** `deep-reasoning` · **Depends on:** 09.1 · **Repo:** `ai-orchestration/`
- **Origin:** owner request (2026-10-17): "come faccio a aprire una nuova feature/bug … servirebbe gestione allegati".
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py`, the task-pipeline `SKILL.md` (document the attachments).
- **Goal:** Spec §7, engine side: the type classes and checks, `inbox attach` accepting them, `kind: feature`, `tasks attach|detach`, `tasks new --from-note` copying attachments with rewritten references, `tasks list`/`show` JSON exposing `attachments: [{name, class, size}]` for tasks and notes.
- **Verification:** tests for each class (accepted and refused: a `.png` that is really text, a `.log` with a NUL byte, a fake PDF), the 30-file limit, traversal names, task bundle hash changes on attach, convert copies attachments and rewrites links; full engine suite green.

### 09.8 - UI backend: task attachment endpoints and per-class serving

- **Status:** `delivered` (2026-10-17; claude; merged (rebased onto 09.5, conflicts resolved: both route sets kept, moved helpers deduplicated); 47 backend tests; per-class headers: image inline, text/plain utf-8, pdf attachment, nosniff) · **Profile:** `bulk-execution` · **Depends on:** 09.7, 09.2 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Spec §7: `POST/GET/DELETE /api/tasks/{id}/attachments[/{name}]` mirroring the inbox ones; serving by class (inline image, `text/plain; charset=utf-8`, PDF as attachment), `nosniff` on all; inbox upload accepts the new classes (the engine decides).
- **Verification:** tests for auth, each class's headers, traversal refusal, 409 on a stale hash.

### 09.9 - Frontend: attachments by class in the note editor and the task detail

- **Status:** `delivered` (2026-10-18; claude; merged: text viewer (pre, React text), PDF download via revoked blob URL, thumbnails, task detail attachments section; Kilo verified on a scratch workspace; owner live check pending) · **Profile:** `bulk-execution` · **Depends on:** 09.3, 09.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`
- **Goal:** Spec §7 UI: thumbnails, text viewer, PDF download chip; paste/drop/picker in the task detail too.
- **Verification:** Playwright on a scratch workspace: attach a `.log` and a `.pdf` to a note and to a task, open the text viewer, convert the note and see the attachments on the new task.

### 09.10 - Edit proposed tasks before accepting a triage proposal

- **Status:** `open` · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 09.4, 09.5 · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/`
- **Origin:** 09.4/09.5 dispatch (2026-10-17): `run accept-triage` takes `--only` but no edits, while spec §4 says each proposed task can be edited before acceptance.
- **Goal:** `run accept-triage ... --edits-file F` (JSON: per proposed task index, overridden title/category/priority/priority_reason/goal/steps/verification, validated like the proposal); the review panel's cards become editable and send the edits.
- **Verification:** engine tests (edited fields land in the created task, invalid edits refused); live: edit one proposed task, accept, the task has the edited title.

### 09.11 - VS Code: handlers for task attachments and triage (parity with 09.5, 09.8, 09.9)

- **Status:** `delivered` (2026-10-18; claude; merged; parity test green; extension 0.3.1 installed) · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 09.6, 09.8, 09.9 · **Repo:** `vscode-ai-orchestration/`
- **Origin:** the bridge-parity test fails after 09.5/09.9: `uploadTaskAttachment`, `getTaskAttachment`, `deleteTaskAttachment`, `getTriageProposal`, `acceptTriage` have no handler (2026-10-18).
- **Goal:** the five handlers, mirroring the web backend and the inbox handlers of 09.6 (validation, temp-file cleanup, realpath containment, per-class content type); `startRun`/`previewRun`/`getRunOptions` accept a `note` target.
- **Verification:** parity test and the extension suite green; a handler test for each.
