# Spec: Inbox — draft notes, reports and screenshots, processed into tasks

- **Status:** draft for review (2026-10-16)
- **Drives:** initiative [09](../09-inbox-notes/plan.md)
- **Builds on:**
  - the `task-pipeline` convention `_inbox/to-analyze/` → `_inbox/analyzed/` (`plugins/architect-side/skills/task-pipeline/SKILL.md`, "The pipeline", step 1–2);
  - [`control-plane-safety`](control-plane-safety.md) (auth, CSP, task-write lock, preview/confirm);
  - [`agent-runs-from-ui`](agent-runs-from-ui.md) (an agent run processes a note);
  - [`blocking-questions`](blocking-questions.md) (the processing agent asks instead of guessing).

## 1. Goal

The owner writes quick notes and reports in the UI, with screenshots pasted or dropped in, without having to structure them. Later, the notes are **processed**: by the owner by hand, or by an agent run. Processing turns them into emergent tasks (`T###`), into a spec, or into an update of an existing task. Each note keeps a link to what it produced.

## 2. Storage (inside the project; the files are the source of truth)

- **One note per folder:** `tasks/_inbox/to-analyze/<YYYYMMDD-HHMMSS>-<slug>/`, containing:
  - `note.md` — header plus free Markdown body;
  - `attachments/` — the images as they were uploaded (`png`, `jpg`, `jpeg`, `gif`, `webp`; others refused), named `<NN>-<sanitized original name>`. Each file is at most 10 MB, and a note holds at most 20 images.
- **Processed or discarded notes** are moved with their folder to `tasks/_inbox/analyzed/<same folder name>/`.
- Plain `.md` files already in `_inbox/to-analyze/` (the current convention) stay valid. They are shown as notes with no header and no attachments; the first save from the UI converts them to the folder form.

**`note.md` header** (same `- key: value` grammar as task headers):

| Field | Values |
| --- | --- |
| `id` | `N###`: unique across `_inbox/`, allocated under the task-write lock (spec 06 A9) |
| `title` | short title, free text |
| `kind` | `note`, `bug`, `feature`, `idea`, `request`, `question` |
| `status` | `draft`, `ready`, `processing`, `processed`, `discarded` |
| `created` | ISO datetime |
| `author` | `owner` or a session name |
| `about` | optional: paths, repos or task ids the note refers to, comma-separated, or `-` |
| `produced` | ids produced by processing (`T014, T015`, a spec path, `Q005`), or `-` |
| `processed-by` | `owner`, `<tool>:<profile> (run <run_id>)`, or `-` |
| `origin-session` | session id or role (`orchestrator`) when created by a registered session, else `-` |

The body follows the header. Images are referenced in Markdown as `![](attachments/01-screen.png)`; the UI inserts these references when an image is pasted.

**Status rules:**

- `draft` is editable.
- `ready` means "can be processed"; it can still be edited.
- `processing` is set while a run works on the note; it is locked against edits.
- `processed` and `discarded` are final; the folder moves to `analyzed/`. A processed note may be reopened, which moves it back to `to-analyze/` as `ready`.

## 3. Engine (`ai-orch inbox`)

In `tasks_engine.py` (stdlib only; every write under the task-write lock and atomic):

| Command | Effect |
| --- | --- |
| `inbox list [--status ...]` | Notes with their header and attachment list. |
| `inbox show N###` | One note: header, body, attachment paths. |
| `inbox add --title T --kind K [--body-file F] [--about X]` | Creates the folder and returns the id. |
| `inbox edit N### [--title] [--kind] [--body-file F] [--status draft\|ready] [--expect-hash H]` | Hash = the note bundle (`note.md` + attachments). |
| `inbox attach N### --file PATH` | Validates the type by magic bytes (not by extension) and the size, copies the file into `attachments/`, and returns the Markdown reference. |
| `inbox detach N### --name NAME` | Removes the attachment. |
| `inbox resolve N### --produced IDS --by WHO` / `inbox discard N### --reason TEXT` | Sets the final status and moves the folder to `analyzed/`. |
| `inbox reopen N###` | Moves the folder back to `to-analyze/` as `ready`. |
| `tasks new --from-note N### ...` | Creates a `T###` task with the standard header and sections. `sources` points to the note, and the note's `about` seeds `paths`. Used by manual processing. |

## 4. Processing

- **Manual (owner).** "Convert to task" opens the task form, pre-filled from the note: title, kind → category hint, `about` → paths, body → Goal. On save the engine creates the `T###` with `tasks new --from-note`. The owner can create several tasks from one note, then "Mark processed" (`inbox resolve`).
- **By an agent (needs initiative 07).** "Process with…" opens the Run dialog in a new run mode **`triage`**.
  - **What the agent receives:** the note (body + attachments). Images are passed as files: Claude reads them with its file tools, Kilo through `-f`, Codex through `-i`.
  - **Context:** the task-pipeline rules for emergent tasks, the current `00-INDEX.md`, and the note's `about` paths.
  - **Mandate:**
    - propose new `T###` tasks, or updates to existing tasks, or a spec;
    - emit them as a structured ` ```ai-orch-triage ` block (JSON: `{"tasks": [ {header fields..., "goal", "steps", "verification"} ], "updates": [...], "spec": null|{...}, "questions": [...]}`);
    - file blocking questions (spec 08) when the note is ambiguous;
    - **never** write task files itself.
  - **The run writes nothing to `tasks/`.**
  - **Review.** The supervisor parses the block, and the UI shows the proposal for review (each proposed task can be edited or rejected). On "Accept", the engine creates the accepted tasks and resolves the note with `produced` and `processed-by`.
  - `triage` runs in the workspace (no worktree), with a read-only permission policy: it reads the repo and writes nothing.

## 5. UI

- **Inbox tab** (navbar badge = count of `draft` + `ready` notes). It lists the notes (title, kind, status, age, thumbnails), with filters by status and kind.
- **Note editor.**
  - Title, kind, `about`, and a Markdown body with a preview.
  - **Paste an image from the clipboard** (`paste` event), or **drag and drop** files, or a file picker → upload → `inbox attach` → the reference is inserted at the cursor.
  - Thumbnails of the attachments, each with remove.
  - Autosave while `draft`, debounced and protected by the hash. On a conflict, the editor shows both versions.
- **Actions:** "Ready", "Convert to task" (manual), "Process with…" (agent, once 07 is available), "Discard" (with a reason), "Reopen".
- **Safety.**
  - Uploads go through an authenticated `POST /api/inbox/{id}/attachments` (spec 06 auth) with a size limit enforced server-side, and the type is checked by magic bytes.
  - Attachments are served by `GET /api/inbox/{id}/attachments/{name}` with `Content-Type` from the sniffed type, `X-Content-Type-Options: nosniff`, and the CSP of spec 06 A12 (`img-src 'self' data: blob:`).
  - Names are validated, with no path traversal.
  - Note bodies are rendered with HTML escaped (spec 06 A12).
- **VS Code.** The same webview tab. Paste works through the webview; uploads go through `postMessage` as base64 chunks to the extension, which calls `ai-orch inbox attach`.

## 6. Out of scope

- OCR or any automatic reading of images outside an agent run.
- Archives and executables as attachments (see §7 for the allowed types).
- Sharing notes outside the project.

## 7. Amendment (2026-10-17, owner request): general attachments, and attachments on tasks

The owner opens bugs and features from the Inbox, and needs to attach more than screenshots (logs, PDFs, config excerpts), also on tasks. Decisions (orchestrator, minor):

- **`kind` gains `feature`.** Conversion maps `bug` → category hint `bugfix`, `feature`/`request` → `feature`.
- **Allowed attachment types** (checked by content, never by extension alone; anything else refused):

| Class | Types | Check | Served as |
| --- | --- | --- | --- |
| image | png, jpeg, gif, webp | magic bytes (as today) | inline, sniffed `Content-Type` |
| text | `.txt .log .md .json .yaml .yml .toml .csv .xml .diff .patch .html .js .ts .py .java .sh` and similar | valid UTF-8, no NUL byte in the first 64 KB | `text/plain; charset=utf-8`, inline (the UI shows it in a `<pre>` viewer, never as HTML) |
| pdf | `.pdf` | starts with `%PDF-` | `application/pdf` with `Content-Disposition: attachment` |

- **Limits:** 10 MB per file (unchanged), at most 30 attachments per note or task. Every response carries `X-Content-Type-Options: nosniff`; names are sanitized as today.
- **Markdown references:** images as `![](attachments/NN-name.png)`, other files as `[NN-name.log](attachments/NN-name.log)`.
- **Attachments on tasks.** An emergent task folder (`<category>/T###-<slug>/`) may hold `attachments/` with the same rules. Engine: `tasks attach T### --file PATH [--name N]` and `tasks detach T### --name N`, under the task-write lock, changing the task bundle hash. Initiative tasks (`NN.T` inside `plan.md`) have no folder and take no attachments; attach to the initiative's folder later if needed (out of scope here).
- **Convert keeps the evidence.** `tasks new --from-note N###` copies the note's attachments into the new task's `attachments/` and rewrites the references in the copied body, so the task stays self-contained after the note moves to `analyzed/`.
- **UI.** The note editor and the task detail show attachments by class: thumbnails for images, a chip that opens a text viewer for text, a download chip for PDFs. Paste, drop and picker accept all allowed types; refused types show the reason.

## 8. Amendment (2026-10-18, spec 12 E10): `origin-session` header field

The `note.md` header gains `origin-session` directly after `processed-by` (values: session id, role name like `orchestrator`, or `-` when absent). This links notes created by an orchestration session back to that session, enabling event filtering and notifications for the originating session. When both an origin run and an origin role exist, the run takes precedence for `resume-origin`.
