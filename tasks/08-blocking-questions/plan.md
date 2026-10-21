# 08 - Blocking questions (format, engine, pending-answers UI)

- **Short:** Blocking questions

> **Derived from:** [`../specs/blocking-questions.md`](../specs/blocking-questions.md). Read the spec first; this plan does not repeat it.

## Waves

| Wave | Tasks |
| --- | --- |
| 1 (after 06.1, same file) | 08.1 |
| 2 | 08.2 (skills), 08.3 (UI backend, after 06.7) in parallel |
| 3 | 08.4 (frontend, after 06.8) |
| 4 | 08.5 (VS Code, after 06.9); 08.6 (answer and resume, after 07.6/07.7) |

## Tasks (One Task = One Commit)

### 08.5 - VS Code: "Decisions Waiting" tree from question files

- **Status:** `delivered` (2026-10-17; merged; awaiting live check in an Extension Development Host) · **Short:** VS Code Decisions tree · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 08.4, 06.9 · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/*decision*`, `src/views/dashboard-panel.ts`, `dist-webview/**`
- **Goal:** Spec §5 "VS Code".
- **Verification:**
  - `npm run compile` is clean.
  - Live: the tree lists open questions, and a click opens the card.

### 08.6 - "Answer and resume run"

- **Status:** `delivered` (2026-10-18; claude; merged; review fix: origin-run validated with RUN_ID_RE before path use; 50 backend tests; live resume with a real agent pending) · **Short:** Answer and resume · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 08.4, 07.7 · **Repo:** `ai-orchestration-ui/` (+ `ai-orchestration/` if the supervisor's question-block filing from 07.3 needs a follow-up)
- **Focus files:** `frontend/src/**`, `backend/server.py`
- **Goal:**
  - spec §5 "Answer and resume run";
  - spec §4 fallback-block filing by the run supervisor, if 07.3 did not already do it.
- **Verification:** Live with a real run (one tool is enough) that is instructed to ask: the question appears; "Answer and resume" continues the same session, and the agent acknowledges the answer.

## Amendments after review 2 (2026-10-16)

The spec now opens with §0 "Amendments after review 2" (Q1–Q10). These changes to the tasks follow from it, and the lane order is in `../06-control-plane-safety/plan.md`:

- **08.1** now depends on **06.10** (task-write lock), not only on 06.1. It also covers Q1–Q7 and Q9. Its live verification uses a **disposable fixture** with legacy `decider: owner: <text>` tasks: T007, T009 and T010 carry `decider: -`, so the earlier plan text was wrong.
- **08.2** documents Q8 for skills: agents in runs emit the block, interactive sessions call `questions ask`.
- **08.4** adds Q10 and spec 06 A12 (XSS fixtures: a `<script>` / `<img onerror>` payload in a question context renders inert).
- **08.6** no longer owns supervisor filing; that moved to **07.10**. 08.6 is UI only: "Answer and resume run", after 07.7, 07.10 and 08.4.

> **2026-10-17:** 08.6 "Answer and resume run" is superseded by initiative 12 (trigger rule `resume-origin` on `question.answered`, task 12.4). It is no longer worked on here.

### 08.7 - VS Code: toast for new questions and a status-bar badge

- **Status:** `delivered` (2026-10-17; merged in vscode-ai-orchestration 0.2.0+, installed; awaiting the owner's live check) · **Short:** Question toasts · **Size:** S · **Depends on:** 08.5 (VS Code lane) · **Repo:** `vscode-ai-orchestration/`
- **Origin:** owner request (2026-10-17).
- **Goal:**
  - A new open question (an id not seen before) shows a VS Code notification (`showInformationMessage`) with its short text and the actions "Open" (reveals the dashboard on the Decisions tab and that question, or at least the tab) and "Later".
  - A status-bar item shows the open-question count (`$(question) N`), with warning background when N > 0 and hidden or neutral when N = 0. Clicking it opens Decisions.
  - No toasts at startup for questions that already exist; only the badge.
  - Notified ids are remembered in `workspaceState`, so a reload never re-notifies.
  - Answered or withdrawn questions update the badge immediately.
  - A setting `aiOrchestration.notifyNewQuestions` (default true).
- **Verification:**
  - `npm run compile` is clean.
  - A test drives the diffing logic (open set before and after, notified-ids store): a new id → one notification; startup with existing ids → none; an answered question → the count decreases.
  - Live in an Extension Development Host with the owner.

## Closed

### 08.1 - Engine: question files, validator, `ai-orch questions list|show|ask|answer|withdraw`, Decisions region from open questions

- **Status:** `done` (2026-10-17) · **Short:** Question engine · **Profile:** `deep-reasoning` · **Depends on:** 06.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../scripts/test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md` (add the question model section)
- **Goal:** Spec §2 and §3 completely:
  - the format and the validator;
  - id allocation under a lock;
  - the task `waiting` linkage and its restoration;
  - `--from-task` conversion;
  - the generated Decisions region.
- **Verification:** Tests:
  - every validator rule (header order, a question without `?` or over 160 characters, an unknown `recommended`, `choice: open` without text or with `open-answer: no`, a `blocks` id that does not exist);
  - `ask` blocks an `in progress` task and `answer` restores it;
  - two concurrent `ask` calls get distinct ids;
  - the Decisions region renders one row per open question;
  - a legacy `decider: owner: ...` still validates with a warning.

  Live: run `questions ask --from-task` on a copy of the workspace `tasks/` for T007, T009 and T010 (which carry legacy decider texts), and review the result.

### 08.2 - Skills: agents file blocking questions in the format

- **Status:** `done` (2026-10-17) · **Short:** Agents file questions · **Profile:** `bulk-execution` · **Depends on:** 08.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/SKILL.md`, `.../task-pipeline/references/template.md`, `plugins/architect-side/skills/orchestration-workflow/SKILL.template.md`, `plugins/executor-side/skills/executor-contract/SKILL.template.md`, the generated `SKILL.md` files (regenerate, never hand-edit), `index.json` files
- **Goal:** Spec §4. Keep the skills protocol-agnostic: name `ai-orch questions ask` as the CLI of this kit (allowed), never a concrete MCP tool. Regenerate the generic skills.
- **Verification:**
  - `python3 ./scripts/regenerate_generic_skills.py && python3 ./scripts/generate_skill_indices.py` is clean.
  - The Final Report flags that `kilo-mcp`'s bound copies need `regenerate_bound_skills.py` (orchestrator follow-up in `../kilo-mcp`).

### 08.3 - UI backend: question endpoints

- **Status:** `done` (2026-10-17) · **Short:** Question endpoints · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 08.1, 06.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Add these endpoints, as thin async wrappers:
  - `GET /api/questions?status&blocks`
  - `GET /api/questions/{id}`
  - `POST /api/questions` (ask)
  - `POST /api/questions/{id}/answer`
  - `POST /api/questions/{id}/withdraw`

  The watcher reports question changes as `areas:["questions"]`.
- **Verification:** HTTP tests for ask → list → answer → task state restored; an invalid answer → 400 with the validator message.

### 08.4 - Frontend: Decisions tab, navbar badge, task-modal Questions section, ask form

- **Status:** `done` (2026-10-17) · **Short:** Decisions tab · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 08.3, 06.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Spec §5, except "Answer and resume run".
- **Verification:**
  - `npm run build` is clean.
  - Live with the Playwright MCP on a scratch workspace: ask a question from the task modal → badge count 1 → answer with an option → the task returns to its previous state; an open answer requires text; Withdraw requires a reason.
