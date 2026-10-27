# Study: Owner Interactions with Registry Elements from the UI (T076)

- **Task:** `T076 (Studio interazioni UI)`
- **Date:** 2026-10-27
- **Status:** Draft for owner review
- **Scope:** `ai-orchestration` (`tasks_engine.py`), `ai-orchestration-ui` (`backend/server.py`, `frontend/src/components/*`), `vscode-ai-orchestration` (`src/*`, webview bridge & sidebar tree views)
- **Related specs & tasks:** `T074 (Chat contestuale per elemento)`, `T075 (Valida e chiudi da UI)`, `T073 (Studio pannello orchestratori)`, Initiative `17` (`use-cases-drive-tasks.md`), `task-and-state-model.md`, `control-plane-safety.md`, `ui-multi-project.md`, `orchestration-extension-spec.md`.

---

## Executive Summary & Guiding Principles

The owner has been requesting individual UI actions one by one:
- *"Validate & close"* on the `Delivered` column header and on individual tasks (`T075`);
- *Contextual AI chat* inside a task, use case, or question view (`T074`, where the AI has full tool access and only the conversation context is scoped to the element);
- *Inline field editing* (2026-10-27: *"e.g. interface to change priority: clicking the current priority opens a menu to change it"*);
- Earlier requests: quick *Pause / Resume* buttons on cards, *Request validation* (`verify-by`), and *Show/hide empty projects*.

Designing these piece by piece has produced an inconsistent interaction model: changing a task's priority works only in the Timeline view and requires 5 clicks including a full-screen diff modal; pausing a task is 1 click on a Kanban card and skips hash checks; validating & closing a delivered task requires opening the detail modal twice (`Approve (Verified)` -> modal closes -> reopen -> `Close Task (Done)`), whereas the CLI engine (`T035`) already supports a single `transition <id> done --verifier owner` walk.

### Guiding Criterion: Speed ("Interagire Velocemente")
1. **One click (or one key) from where the element is seen:** Frequent actions and short-field edits happen **in place** on the card, queue row, tree node, or detail header via inline popovers, hover quick-actions, context menus, and keyboard shortcuts—never forcing a view change or modal round-trip.
2. **Inline-Edit Everywhere Pattern:** Clicking any short metadata pill (`priority`, `state`, `executor`, `size`, `kind`, `verify-by`, `use-cases`, `labels`, `next-up`, `approval` on use cases) anywhere it is rendered opens a lightweight popover showing **only valid values** for that element/state. Selecting a value executes the engine's preview+hash+apply transaction **automatically under the hood** (`--dry-run` -> `expect_hash` apply) and shows a non-blocking toast with a 1-click **`[Undo]`**. If a field requires a reason (`priority-reason` on emergent tasks, `reason` on `bounced`/`dropped`/`reopen`), the popover includes a compact inline text input (`Enter` to submit).
3. **Confirmation only for destructive or bulk actions:** Single-item reversible mutations apply immediately with toast undo. Confirmation dialogs are reserved strictly for (a) **bulk actions** (column header actions showing the affected item list + optional note), (b) **destructive actions** (`discard` note, `withdraw` question, `drop` task, `clean` worktree), and (c) **structural/multi-file rewrites** (`sync-index`, `adopt-links`, `expand`/`collapse`, `AGENTS.md`).

---

## 1. Inventory: Engine Actions vs. Web UI & VS Code Extension Coverage

The table below maps every registry element (`EmergentTask` `T###`, `InitiativeTask` `NN.T`, `Microtask`, `Initiative` `NN`, `UseCase` `UC###`, `Question` `Q###`, `InboxNote` `N###`) and its states to the available `tasks_engine.py` commands, current Web UI coverage (`ai-orchestration-ui`), and VS Code Extension coverage (`vscode-ai-orchestration` Webview Dashboard + native Sidebar TreeViews).

### 1.1 Tasks (`EmergentTask` `T###`, `InitiativeTask` `NN.T`, `Microtask`, `Initiative` `NN`)

| Element & StateScope | Owner Action | Engine CLI Command (`ai-orch tasks ...`) | Web UI Coverage (Where) | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Any Leaf Task** (`open`) | **Start task** (`-> in progress`) | `transition <id> "in progress" --actor owner` | `TaskDetailModal` footer (*only* for `NN.T`; hidden for `T###` where only `Run…` is shown!) | Webview only; missing in Sidebar TreeView |
| **Any Leaf Task** (`open`, `in progress`, `bounced`, `delivered`) | **Launch Agent Run** (implement / verify) | `ai-orch run start --task <id> ...` | `TaskDetailModal` footer (`Run…`) & `TaskRunsPanel` | Webview only |
| **Any Leaf Task** (`open`, `in progress`, `waiting`, `blocked`, `bounced`, `delivered`) | **Pause task** (`-> paused`) | `transition <id> paused --actor owner` | Kanban card icon, Queue row button, `TaskDetailModal` footer (missing in Tree & Timeline) | Webview only |
| **Any Leaf Task** (`paused`) | **Resume task** (`-> open` or `in progress`) | `transition <id> open\|"in progress" --actor owner` | Kanban card (`-> open`), Queue row (`-> open`), `TaskDetailModal` (`Resume (Open)` & `Resume (In Progress)`) | Webview only |
| **Any Leaf Task** (`in progress`) | **Mark Delivered** (`-> delivered`) | `transition <id> delivered [--verify-by <target>] [--verify-check <text>]` | `TaskDetailModal` footer (only if `taskRuns.length === 0`) or `TaskRunsPanel` (`Mark Delivered`); no `verify-by` input | Webview only |
| **Any Leaf Task** (`open`, `in progress`) | **Mark Waiting / Set `waiting-on`** | `transition <id> waiting --waiting-on <qual>` / `set-waiting-on <id> <qual>` | **Missing** (only reachable indirectly by creating a `Q###` question) | **Missing** |
| **Any Leaf Task** (`waiting`) | **Force Unblock** (`-> open`/`in progress`) | `transition <id> open --force-unblock --reason <text>` | **Missing** in UI and backend | **Missing** |
| **Any Leaf Task** (`open`, `in progress`) | **Mark Blocked** (`-> blocked`) | `transition <id> blocked --reason <text>` | **Missing** in UI | **Missing** |
| **Any Leaf Task** (`delivered`) | **Approve / Mark Verified** (`-> verified`) | `transition <id> verified --verifier owner --owner-approved --reason <text>` | `TaskDetailModal` footer (`Approve (Verified)`, passes `verifier="operator:owner"`) | Webview only |
| **Any Leaf Task** (`delivered`) | **Validate & Close (1-shot)** (`delivered -> verified -> done`) | `transition <id> done --verifier owner [--reason <text>]` or `close <id> --verifier owner` (`T035`) | **Missing** (`T075` requested: needed on Kanban column, card, and detail) | **Missing** |
| **Any Leaf Task** (`delivered`, `in progress`) | **Close as Self-Verified Caveat** (`-> done with a caveat`) | `close <id> --self-verified` or `close <id> --caveat <text>` (`T035`) | **Missing** in UI and backend | **Missing** |
| **Any Leaf Task** (`delivered`) | **Bounce to Executor** (`-> bounced`) | `transition <id> bounced --reason <B1..Bn>` | `TaskDetailModal` footer (`Bounce` -> inline textarea) | Webview only |
| **Any Leaf Task** (`verified`) | **Close Task** (`-> done`) | `transition <id> done --actor owner` or `close <id>` | `TaskDetailModal` footer (`Close Task (Done)`) | Webview only |
| **Bulk (`delivered` / `verified`)** | **Bulk Validate & Close / Close Verified** | `close --verified [--dry-run] [--expect-plan-hash <h>]` (`T035`) + loop/batch for `delivered` | **Missing** (`T075` requested on `Delivered / Verified` column headers) | **Missing** |
| **Any Leaf Task** (non-terminal) | **Drop Task** (`-> dropped`) | `transition <id> dropped --reason <text>` | **Missing** in UI (cannot drop a task from UI!) | **Missing** |
| **Any Leaf Task** (`done`, `done with a caveat`, `dropped`) | **Reopen to Open** (`-> open`) | `reopen <id> --to open --reason <text> [--expect-plan-hash <h>]` | `TaskTreeView` row button (`Reopen`); **missing** in `TaskDetailModal` and Kanban `Done` column! | Webview (`TaskTreeView` only) |
| **Any Leaf Task** (`done`, `done with a caveat`, `dropped`) | **Reopen to Delivered + Request Verification** (`-> delivered`) | `reopen <id> --to delivered --verify-by <target> [--verify-check <text>] --reason <text>` (`T063`) | **Missing** in UI and backend (backend `/reopen` does not pass `--to` or `--verify-by`) | **Missing** |
| **Any Task** (any state) | **Set Priority** (`P0`–`P3` + `priority-reason`) | `set-priority <id> <P0-P3> [--reason <text>] [--dry-run] [--expect-task-hash <h>]` | `TimelineCard` only (opens popover -> then opens full `ConfirmDialog` diff modal!); **read-only** in Kanban, Queue, Tree, and `TaskDetailModal`! | Webview (`TimelineCard` only) |
| **Any Task** (any state) | **Set Size** (`XS`–`XL`) | `set-size <id> <XS-XL> [--dry-run] [--expect-task-hash <h>]` | `TimelineCard` only (popover -> full `ConfirmDialog` modal); read-only elsewhere | Webview (`TimelineCard` only) |
| **Any Task** (any state) | **Set Executor / Assignee** | `set-executor <id> <executor> [--dry-run] [--expect-task-hash <h>]` | **Missing in UI and backend!** (`server.py` has no `/executor` route; UI displays `executor` as static text everywhere) | **Missing** |
| **Any Task** (`delivered` or any) | **Request Verification (`verify-by` + `check`)** | `set-verify-by <id> <target> [--check <text>]` / `request-verification` (`T044`) | **Missing in UI and backend!** (`server.py` has no `/verify-by` or `/verification-queue` route) | **Missing** |
| **Any Task** (any state) | **Set Kind** (`feature`, `bug`, `fix`, `chore`, `docs`, `investigation`) | `set-kind <id> <kind> [--dry-run] [--expect-task-hash <h>]` | Backend route & `api.setKind` exist, **but no UI component calls `setKind`!** `KindBadge` is non-clickable everywhere | **Missing** (bridge exists, no UI trigger) |
| **Any Task** (any state) | **Edit Labels** (`add`/`remove`/`to`) | `set-labels <id> --to <labels...> [--dry-run] [--expect-task-hash <h>]` | `TaskDetailModal` (`Edit` link -> `LabelEditorModal` -> `ConfirmDialog`: 6 clicks) | Webview (`TaskDetailModal` only) |
| **Any Task** (any state) | **Edit Short Title** (`short`) | `set-short <id> <short> [--dry-run] [--expect-task-hash <h>]` | `TaskDetailModal` header (inline input, auto preview+apply in 2 clicks — good model!) | Webview (`TaskDetailModal` only) |
| **Any Task** (any state) | **Edit Dependencies** (`depends-on`) | `set-deps <id> --add/--remove [--dry-run] [--expect-task-hash <h>]` | `TimelineCard` only (`+ Add` / `×` -> full `ConfirmDialog` modal); read-only in `TaskDetailModal` | Webview (`TimelineCard` only) |
| **Any Task** (any state) | **Link / Unlink Use Cases** (`use-cases`) | `link <id> UC###` / `unlink <id> UC###` (Spec 17 `17.2`) | **Missing** (planned in `17.9`–`17.10`) | **Missing** |
| **Emergent Task** (`T###`) | **Toggle `next-up` (`yes`\|`no`)** | Header field `next-up: yes\|no` *(needs `set-next-up` subcommand in engine)* | **Missing!** Queue empty-state tells user to edit Markdown by hand (`**Next up:** yes`) | **Missing** |
| **Emergent Task** (`T###`) | **Checklist Steps (`## Steps`)** | `step list\|add\|check\|uncheck <id> ...` (`T036`) | **Missing in UI and backend!** Steps are rendered as static Markdown checkboxes | **Missing** |
| **Emergent Task** (`T###`) | **Move to another project** | `move <id> --to-project <slug> [--dry-run] [--expect-task-hash <h>]` | **Missing in UI and backend!** Placement warning chip shows warning but offers no 1-click move | **Missing** |
| **Emergent Task** (`T###`) | **Attach / Detach files** | `attach <id> --file <f>` / `detach <id> --name <n>` | `TaskDetailModal` drag-drop & `Attach…` / `×` (uses `window.confirm` on delete) | Webview only |
| **Microtask** (`tasks/micro/T###`) | **Create / Promote to full task** | `micro --title ...` / `promote <id> [--category <c>]` | `MicrotaskQuickAdd` in Backlog/Timeline; `Promote` button on `TimelineCard`, `TaskTreeView`, `TaskDetailModal` | Webview only |
| **Container / Open Leaf** | **Add Child Subtask / Expand / Collapse** | `child add <parent> --title ...` / `expand <id>` / `collapse <id>` | `TaskTreeView` row buttons & `TaskDetailModal` footer | Webview only |
| **Initiative** (`NN` all leaves done) | **Ship Initiative to `done/NN-slug/`** | `ship <NN> [--dry-run] [--expect-plan-hash <h>]` | **Missing in UI and backend!** | **Missing** |
| **Any Task** (any state) | **Copy Handoff / Open File** | `show <id>` (`handoff`, `file_path`) | Queue row (`Handoff`), Tree row (copy icon), `TaskDetailModal` (`Copy Prompt`); missing on Kanban card | Sidebar TreeView inline icons (`copyHandoff`, `openTaskFile`) + Webview |
| **Any Task** (any state) | **Contextual AI Chat on Task** (`T074`) | Enqueue/send scoped chat turn with task + linked UC/spec/question/run context | **Missing** (`T074`: today `OrchestratorChatPanel` is global-only) | **Missing** |

### 1.2 Use Cases (`UC###`)

| Element & State / Stage (Spec 15 + Spec 17) | Owner Action | Engine CLI Command (`ai-orch tasks use-cases ...`) | Web UI Coverage (Where) | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Use Case** (any) | **Create / Edit Use Case** | `use-cases create [--id UC###] --title ...` | `UseCasesManager` (`New Use Case` modal); **no Edit UI** for existing use cases! | Webview (Create only); Sidebar TreeView opens raw `.md` file |
| **Use Case** (`approval: proposed\|approved\|deprecated`, Spec 17 §3) | **Approve / Deprecate Use Case** | `use-cases set-approval <UC> approved\|deprecated\|proposed` *(Spec 17 `17.5`)* | **Missing** (today `createUseCase` hardcodes `status: 'active'`) | **Missing** |
| **Use Case** (`stage: ready\|verified\|failing`) | **Run Automated Validation Probe** | `use-cases validate <UC> [--force] [--timeout 60]` | `UseCasesManager` card (`Validate with AI`) & `UseCaseDetailModal` footer (uses `alert()` on error; no `--force` option for non-ready UCs) | Webview only (missing in `useCasesView` sidebar context menu) |
| **Use Case** (any) | **Record Owner / Manual Validation Verdict** | `use-cases record-validation <UC> --verdict pass\|fail\|partial --summary ... --actor owner` | **Missing in UI and backend!** Only automated probe `validate` is wired | **Missing** |
| **Use Case** (any) | **Create Task from Use Case** (pre-filled Goal & Verification) | `tasks new --from-use-case <UC> [--steps 2-3] ...` (Spec 17 §2 `17.4`) | **Missing** (planned in Initiative 17) | **Missing** |
| **Use Case** (any) | **Link / Unlink Existing Task** | `tasks link <task> <UC>` / `tasks unlink <task> <UC>` (Spec 17 §1 `17.2`) | **Missing** (currently linked task pills in `UseCasesManager` & `UseCaseDetailModal` are non-clickable static spans!) | **Missing** |
| **Use Case** (all ready UCs) | **Run Validation Campaign** | `use-cases campaign [--filter-actor <a>]` | `UseCasesManager` header (`Run Product Validation Campaign`) | Webview only |
| **Use Case** (any) | **Edit Short Title / Priority / Actor** | `set-short <UC> <short>` / `use-cases create --id <UC> ...` | **Missing** in `UseCaseDetailModal` | **Missing** |
| **Use Case** (any) | **Contextual AI Chat on Use Case** (`T074`) | Scoped AI chat with UC + linked tasks + validation log | **Missing** (`T074`) | **Missing** |

### 1.3 Blocking & Non-Blocking Questions (`Q###`)

| Element & Status | Owner Action | Engine CLI Command (`ai-orch tasks questions ...`) | Web UI Coverage (Where) | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Question** (new) | **Ask a Question** (blocking or `--blocks -`) | `questions ask --question "...?" --blocks <ids\|-> ...` | `TaskDetailModal` (`Ask a question…` form, always blocks that task); **no standalone "Ask Question" button** in `DecisionsTab`! | Webview (`TaskDetailModal` only) |
| **Question** (`open`) | **Answer Question** (pick option `A..Z` or `open` + optional note) | `questions answer <Q###> --choice <c> [--text <t>] --by owner [--apply-ref <r>] [--changes-result]` | `DecisionsTab` -> `Open Decisions` card radio + `Answer` -> `ConfirmDialog` (3 clicks; **missing** in `TaskDetailModal` where open questions are shown read-only!) | Sidebar `decisionsView` click opens `DecisionsTab` in Webview |
| **Question** (`open` with `origin-run`) | **Answer & Resume Origin Run** | `questions answer` + `run continue` (`/answer-and-resume`) | `DecisionsTab` (`Answer and resume run` -> `ConfirmDialog`) | Webview |
| **Question** (`open`, conditional on done task) | **Answer with `--changes-result`** (spawns follow-up task) | `questions answer <Q###> --choice <c> --changes-result` (`T030`) | **Missing in UI!** Checkbox for `--changes-result` is not exposed in `DecisionsTab` | **Missing** |
| **Question** (`open`) | **Withdraw Question** | `questions withdraw <Q###> --reason <text> --by owner` | `DecisionsTab` (`Withdraw Question…` modal) | Webview |
| **Question** (`answered`, `applied: false`) | **Record Decision Applied** | `questions apply <Q###> --by owner [--ref <ref>] [--note <note>]` (`T041`) | `DecisionsTab` -> `Awaiting Application` sub-tab (`Apply Decision` modal); also needs 1-click *"Answer & mark applied"* when owner answers directly | Webview |
| **Question** (`open` or `answered --force`) | **Move to External Tracker** (`status: moved`) | `questions move <Q###> --to <url> [--reason <r>] [--force]` (`T041`, `T052`) | **Missing in UI and backend!** (`server.py` has no `/move` route; `DecisionsTab` filters only `answered \| withdrawn`, hiding `moved` questions!) | **Missing** |
| **Question** (any) | **Contextual AI Chat on Question** (`T074`) | Scoped AI chat with question options + blocked tasks + specs | **Missing** (`T074`: owner cannot discuss trade-offs with AI right inside the question card before answering) | **Missing** |

### 1.4 Inbox Notes (`N###`)

| Element & Status | Owner Action | Engine CLI Command (`ai-orch tasks inbox ...`) | Web UI Coverage (Where) | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Inbox Note** (new / `draft` / `ready`) | **Add / Edit Note & Attachments** | `inbox add ...` / `inbox edit <N###> --expect-hash <h>` / `attach` / `detach` | `InboxPanel` (`New note` / `NoteEditorModal` with autosave + drag-drop attachments) | Webview only (no Inbox TreeView in VS Code sidebar) |
| **Inbox Note** (`draft` / `ready`) | **Toggle `draft` <-> `ready`** | `inbox edit <N###> --status ready\|draft` | Inside `NoteEditorModal` dropdown only; **no 1-click toggle on the list row** | Webview |
| **Inbox Note** (`draft` / `ready`) | **Convert to Full Task / Microtask** | `new --from-note <N###> ...` / `inboxToMicrotask` | Inside `NoteEditorModal` (`Convert to Task…` / `Microtask`) | Webview |
| **Inbox Note** (`draft` / `ready`) | **Convert to Use Case** (Spec 17 use-case-first) | `use-cases create` + `inbox resolve <N###> --produced UC###` | **Missing!** Inbox only converts to Task or Microtask, not Use Case | **Missing** |
| **Inbox Note** (`draft` / `ready`) | **Run AI Triage & Accept Proposal** | `run start --note <N###> --mode triage` / `accept-triage` | Inside `NoteEditorModal` (`Triage with Agent…`, per-card accept/reject/edit) | Webview |
| **Inbox Note** (`draft` / `ready` / `processing`) | **Resolve (Mark Processed) / Discard** | `inbox resolve <N###> --produced <ids>` / `inbox discard <N###> --reason <r>` | Inside `NoteEditorModal` only; **no quick action or bulk discard on `InboxPanel` rows** | Webview |
| **Inbox Note** (`processed` / `discarded`) | **Reopen Note** (`-> to-analyze/ as ready`) | `inbox reopen <N###>` | Inside `NoteEditorModal` only | Webview |

---

## 2. Gaps, Friction Points, and Inconsistencies

### 2.1 Speed & Click-Count Bottlenecks (Violations of the Guiding Criterion)
1. **Inline field editing is missing across 90% of the UI, and over-confirmed where it exists:**
   - In **Kanban**, **Queue**, **Tree**, and **TaskDetailModal**, `priority`, `size`, `executor`, `kind`, `verify-by`, and `use-cases` are **static, non-interactive text**.
   - Only `TimelineCard` has a popover for `priority` and `size`, **but clicking a new size or priority in `TimelineCard` opens a full-screen `ConfirmDialog` showing a raw unified diff (`TimelineView.tsx:331-372`)**! Changing a task from `P2` to `P1` in Timeline takes **5 clicks + typing**: (1) click `P2` pill, (2) click `P1` in popover, (3) type optional reason, (4) click `Preview`, (5) click `Apply` in the full-screen modal.
   - By contrast, editing `short_title` in `TaskDetailModal` (`TaskDetailModal.tsx:287-318`) runs `previewSetShortTitle` -> `setShortTitle(expect_plan_hash)` **automatically in one step** without a modal. That automatic preview+hash pattern should be the universal rule for all single-field inline edits.
2. **Validating and closing a delivered task takes 5–6 clicks and two modal openings (or is impossible in bulk):**
   - Today, on a `delivered` card: (1) click card to open `TaskDetailModal`, (2) click `Approve (Verified)` — *which immediately closes the modal (`onClose()` at line 715)*, (3) find the card again in the `Verified` sub-column and click it to reopen `TaskDetailModal`, (4) click `Close Task (Done)`.
   - If 8 tasks are sitting in `Delivered — needs verification` after the owner tested the build, closing them takes **32+ clicks**. There is no `Validate & close` button on the card, no `Validate & close` button in `TaskDetailModal`, and no bulk action on the `Delivered` or `Verified` column headers (`T075`).
3. **Answering a question Blocking a Task requires switching tabs:**
   - In `TaskDetailModal`, the `Questions` section lists open blocking questions (`TaskDetailModal.tsx:1510-1570`) **as read-only cards** with no option radio buttons or `Answer` button. The owner has to close the task modal, switch to the `Decisions` tab in the Navbar, find the question, select an option, click `Answer`, and click `Apply` in `ConfirmDialog`.
4. **Linked pills are dead ends (non-clickable):**
   - In `UseCasesManager` and `UseCaseDetailModal`, `Task T012` pills are plain `<span>` elements (`UseCaseDetailModal.tsx:146-158`) — clicking them does not open `T012` (in fact, on `UseCasesManager` cards, clicking a task pill triggers the card's `onClick` and opens the Use Case modal instead!).
   - In `DecisionsTab`, `Blocked Tasks: T012 (short)` pills (`DecisionsTab.tsx:319-351`) are non-clickable `<span>`s.

### 2.2 Missing Engine Capabilities in UI & Backend
- **CLI-only task mutations (no backend route, no UI):** `set-executor`, `set-verify-by` / `request-verification`, `verification-queue`, `set-waiting-on`, `step list/add/check/uncheck`, `move --to-project`, `ship <initiative>`, `close --verified`, `close --self-verified`, `close --caveat`, `transition ... --force-unblock`, `reopen --to delivered --verify-by`.
- **CLI-only question mutations:** `questions move --to <url>` (`T041`/`T052`), `questions answer --changes-result` (`T030`), `questions answer --apply-ref` (1-step answer+apply). Furthermore, `DecisionsTab` history filter (`'all' | 'answered' | 'withdrawn'`) omits `'moved'`.
- **CLI-only use-case mutations:** `use-cases record-validation` (owner manual pass/fail/partial verdict), `use-cases edit` (updating title, actor, priority, scenario, or `verification_command` of an existing UC without recreating it), plus Spec 17's `approval` (`proposed` -> `approved` -> `deprecated`), `tasks link`/`unlink`, and `tasks new --from-use-case`.
- **Missing engine subcommand for `next-up`:** `tasks_engine.py` has `new --next-up yes|no`, `set-priority`, `set-size`, `set-kind`, `set-labels`, `set-short`, `set-executor`, `set-verify-by`, `set-waiting-on`, but **no `set-next-up <id> yes|no`** command! Adding `set-next-up` (or `--next-up` on `set-priority`) lets the owner star/unstar tasks into the Queue in 1 click.

### 2.3 Wording, Actor/Verifier, and Confirmation Inconsistencies
1. **Inconsistent Actor & Verifier strings:**
   - `api.transitionTask` defaults to `actor = 'operator'`.
   - `TaskDetailModal` line 2333 passes `verifier = 'operator:owner'` and `reason = 'Verified by human operator in UI'`.
   - `DecisionsTab` and `T035`/`T075` use `owner` (`--verifier owner`, `--by owner`, `--actor owner`).
   - **Rule to standardize:** Every human action from the Web UI or VS Code Extension must pass `--actor owner` (and `--verifier owner --owner-approved` when verifying/closing).
2. **Inconsistent State & Action Labels:**
   - `open -> in progress`: `TaskDetailModal` shows `Run…` for `T###` (hiding manual `Start Task`!) and `Start Task (In Progress)` for `NN.T`.
   - `delivered -> verified`: `TaskDetailModal` calls it `Approve (Verified)`, `TaskRunsPanel` calls it `Apply Verdict`, CLI calls it `Verify`.
   - `verified -> done`: `TaskDetailModal` calls it `Close Task (Done)`, T075 calls the combined action `Validate & close`.
3. **Confirmation Whiplash (Too much vs. Too little):**
   - *Too much:* Changing `size` or `priority` on `TimelineCard` pops up a 920px modal with a unified git diff.
   - *Too little / wrong mechanism:* Clicking `Pause` on a Kanban card (`BacklogManager.tsx:210-224`) calls `api.transitionTask` without `expectTaskHash` and with no undo toast; deleting a task attachment (`TaskDetailModal.tsx:475`) uses browser `window.confirm()`, and `UseCasesManager`/`UseCaseDetailModal`/`TaskTreeView` use `window.alert()`, which `control-plane-safety.md` §1 V3 & §2.4 explicitly forbade because VS Code webviews block `alert()`/`confirm()`.
4. **Web UI vs. VS Code Sidebar TreeView Parity:**
   - The VS Code Dashboard Webview shares the React frontend (`dist-webview`), so every Webview improvement lands in both once `dashboard-panel.ts` handlers are in parity.
   - However, the **VS Code Sidebar TreeViews** (`nextUpView`, `initiativesView`, `decisionsView`, `useCasesView` in `package.json`) only have **2 context-menu commands** (`Copy Handoff Prompt` and `Open Task File` on `taskItem`). Clicking a task in `nextUpView` opens the raw `.md` file in the editor instead of opening the task in the Dashboard or offering quick inline context-menu actions (`Validate & Close`, `Pause / Resume`, `Set Priority`, `Chat on Element`, `Validate Use Case`).

---

## 3. Interaction Model Proposal (Speed-First & Inline-Everywhere)

### 3.1 Core Design: The "Inline-Edit & 1-Click Action" Architecture

Every interaction is governed by two rules from the owner's 2026-10-27 addendum:
1. **Speed (1 click / 1 key from current view, zero view switching):** If the owner sees a badge or an item, they can act on it right there.
2. **Silent Preview-Hash-Apply + Toast Undo:** The safety invariant of `control-plane-safety.md` (atomic lock + `expect_task_hash` / `expect_plan_hash`) is preserved **100%**, but for single-item field edits and reversible transitions, the frontend performs the preview+apply handshake **transparently in the background** (or passes the already-loaded `task.task_bundle_sha256` directly to the apply endpoint) and surfaces a bottom-right **Action Toast** with a 1-click **`[Undo]`** button (which runs the inverse command: previous field value, `transition` back, or `reopen`).

### 3.2 Universal Inline-Edit Popover Pattern (`<InlineFieldPopover>`)

Wherever a short field is rendered—on a **Kanban card**, **Queue row**, **Tree row**, **Timeline card**, **Task detail header**, **Use Case card/detail**, or **Question card**—it is a clickable pill with a subtle hover border and chevron:

| Field Pill | Appears On | Valid Values Shown in Popover | Extra Inline Input in Popover | Engine Command Executed (Auto Preview/Hash) | Undo Action in Toast |
| --- | --- | --- | --- | --- | --- |
| **Priority** (`P0`..`P3`) | Task card, Queue, Tree, Timeline, Task Detail, UC card/detail | `P0 (Urgent)`, `P1 (High)`, `P2 (Normal)`, `P3 (Low)` | Compact `Reason` input (pre-filled with current `priority_reason`; required only if empty on emergent task, `Enter` saves) | `tasks set-priority <id> <P> --reason <r> --expect-task-hash <h>` | `set-priority <id> <old_P> --reason <old_r>` |
| **State** (`open`, etc.) | Queue, Tree, Timeline, Task Detail, Kanban card context | **Only legal target states** from current state (e.g. from `delivered`: `Validate & Close (done)`, `Mark Verified`, `Bounce…`, `Pause`) | Inline `reason` / `note` input when target is `bounced`, `blocked`, `dropped`, `done with a caveat`, or `reopen` | `tasks transition <id> <target> --actor owner [--verifier owner] [--reason <r>] --expect-task-hash <h>` | `transition` back or `reopen <id> --to <old_state>` |
| **Executor** (`kilo`, etc.) | Task card, Queue, Tree, Task Detail | Configured tools (`kilo`, `claude`, `codex`, `self`, `user-decision`) + discovered live sessions (`session:<name>`) + `workspace:<slug>` | Optional filter input | `tasks set-executor <id> <exec> --expect-task-hash <h>` | `set-executor <id> <old_exec>` |
| **Size** (`XS`..`XL`) | Queue, Tree, Timeline, Task Detail | `XS (1)`, `S (2)`, `M (3)`, `L (5)`, `XL (8)` | None (instant 1-click on option) | `tasks set-size <id> <S> --expect-task-hash <h>` | `set-size <id> <old_S>` |
| **Kind** (`feature`, etc.) | Task card, Queue, Tree, Timeline, Task Detail | `feature`, `bug`, `fix`, `chore`, `docs`, `investigation` | None (instant 1-click on option) | `tasks set-kind <id> <K> --expect-task-hash <h>` | `set-kind <id> <old_K>` |
| **Verify-by** (`verify-by`) | Delivered card, Task Detail | `owner`, configured workspaces (`gcube_atlas`, ...), active sessions (`session:...`), or `- (clear)` | Optional 1-line `What to check` input (`--check`) | `tasks set-verify-by <id> <target> [--check <c>] --expect-task-hash <h>` | `set-verify-by <id> "<old>"` |
| **Use Cases** (`UC###`) | Task card, Queue, Tree, Task Detail | Multi-select checklist of project's `UC### (short title)` with search filter + `+ New Use Case…` | Search box | `tasks link <id> <UC>` / `tasks unlink <id> <UC>` | Inverse `unlink` / `link` |
| **Labels** (`labels`) | Task card (`+` chip), Queue, Tree, Task Detail | Multi-select checklist of existing labels + type-to-create new `[a-z0-9-]+` tag | Tag filter/create input | `tasks set-labels <id> --add/--remove <lbl> --expect-task-hash <h>` | Inverse `--remove` / `--add` |
| **Next-up** (`★` star) | Task card, Queue, Tree, Task Detail | 1-click toggle (`yes` <-> `no`) | None | `tasks set-next-up <id> yes\|no --expect-task-hash <h>` | Toggle back |
| **UC Approval** (`proposed` / `approved` / `deprecated`) | Use Case card, Use Case Detail | `proposed`, `approved`, `deprecated` | None (instant 1-click) | `tasks use-cases set-approval <UC> <val>` | Restore `<old_val>` |

### 3.3 Where Actions Live (5 Interaction Surfaces)

1. **Column / Section Header (Bulk Actions on Visible Items):**
   - Acts on all currently visible (filtered) cards in that column or section.
   - **Delivered sub-header:** `[✓✓ Validate & Close All (N)]` (`T075`), `[⊳ Request Verification (N)…]`.
   - **Verified sub-header:** `[✓ Close All Verified (N)]` (`tasks close --verified`).
   - **Open / Ready header:** `[⏸ Pause All Visible (N)]`.
   - **Paused header:** `[▶ Resume All Visible (N)]`.
   - **Decisions `Awaiting Application` header:** `[✓ Mark All Applied (N)]`.
   - **Inbox `To Analyze` header:** `[✓ Triage Selected / Discard Selected]`.
2. **Card / Row Quick Actions (1-Click Primary Action + Inline Pills):**
   - Every card (Kanban, Use Case, Question) and row (Queue, Tree, Inbox) exposes:
     - **Clickable inline pills** for `Priority`, `Kind`, `Executor`, `Size`, `Use Cases`, `Labels`, `Next-up ★`.
     - **State-specific primary 1-click button** on the right/footer of the card:
       - On `open`: `[▶ Start]` (or `[▶ Run…]`) + `[⏸]`
       - On `in progress`: `[✓ Deliver]` + `[⏸]`
       - On `waiting`: `[💬 Answer Q###]` (opens inline question popover or focuses question!)
       - On `delivered`: **`[✓✓ Validate & Close]`** (primary green button, 1 click!) + `[↩ Bounce]` + `[💬]`
       - On `verified`: **`[✓ Close]`** (1 click!)
       - On `paused`: **`[▶ Resume]`** (1 click!)
       - On `done` / `dropped`: **`[↺ Reopen]`**
     - **Contextual Chat button `[💬]`** (`T074`): opens the slide-over Contextual AI Chat drawer anchored to that element without leaving the board.
3. **Context Menu (Right-Click or `[⋯]` Button on Any Card / Row / VS Code Tree Item):**
   - Provides the full action set for that element without opening the detail modal: *Validate & Close*, *Validate & Close with Note…*, *Approve (Verified only)*, *Bounce…*, *Request Verification (`verify-by`)…*, *Set Priority ▸*, *Set Executor ▸*, *Set Kind ▸*, *Link Use Case ▸*, *Move to Project ▸*, *Add Subtask…*, *Copy Handoff*, *Open Markdown File*, *Drop Task…*, *Chat with AI on this Element*.
4. **Detail View (`TaskDetailModal`, `UseCaseDetailModal`, Question Card, `NoteEditorModal`):**
   - **Header:** All metadata pills are inline-editable (`Priority`, `State`, `Kind`, `Size`, `Executor`, `Profile`, `Verification Mode`, `Verify-by`, `Use Cases`, `Labels`, `Short Title`).
   - **Interactive Body:** In `TaskDetailModal`, `## Steps` checkboxes (`- [ ]` / `- [x]`) are clickable in place (calling `ai-orch tasks step check/uncheck`), with an `+ Add step…` inline input at the bottom of the list. Open blocking `Q###` questions inside `TaskDetailModal` render their option radio buttons and `[Answer]` button **inline** so the owner never has to leave the task modal.
   - **Contextual AI Chat Drawer / Box (`T074`):** Persistent bottom/side chat box scoped to the element.
   - **Sticky Action Bar Footer:** Primary transition buttons (`[✓✓ Validate & Close]`, `[✓ Approve (Verified)]`, `[↩ Bounce…]`, `[▶ Run…]`, `[⏸ Pause]`, `[↺ Reopen…]`, `[🗑 Drop…]`).
5. **Keyboard Shortcuts (When Hovering or Focusing a Card / Row / Detail Modal):**
   - `v` — **Validate & Close** (on `delivered` or `verified` task); on Use Case: **Validate with AI**.
   - `p` — **Priority** menu (`1`=`P0`, `2`=`P1`, `3`=`P2`, `4`=`P3`).
   - `e` — **Executor** menu.
   - `s` — **State** transition menu.
   - `l` — **Labels** popover.
   - `u` — **Use Cases** link popover.
   - `c` — **Contextual AI Chat** on focused element (`T074`).
   - `Space` — Toggle **Pause / Resume** (or check/uncheck focused step).
   - `Cmd/Ctrl+Enter` — Submit active inline input / confirm dialog.

### 3.4 Confirmation Levels & Feedback

| Level | When Used | UX Mechanism | Safety & Audit Under the Hood |
| --- | --- | --- | --- |
| **Level 0: Immediate + Toast Undo** | Single-item inline field edits (`priority`, `size`, `kind`, `executor`, `labels`, `use-cases`, `short`, `next-up`, `verify-by`, `step check`), single-item forward transitions (`Start`, `Pause`, `Resume`, `Approve Verified`, **`Validate & Close` on a single card**), `Copy Handoff`. | Applies immediately on click. Shows a 5-second toast: `✓ T075 validated & closed (owner) [Add Note…] [Undo]`. | Sends `expect_task_hash` (from card's `task_bundle_sha256`). If 409 stale, auto-refetches and retries or shows conflict toast. `[Add Note…]` in the toast or a split-button dropdown `[✓✓ Validate & Close ▾]` lets the owner attach a custom verification note when desired. |
| **Level 1: Inline Micro-Prompt (Popover)** | Single-item actions that **require a mandatory reason/input** by engine guard: `Bounce` (`B1..Bn`), `Drop` (`reason`), `Block` (`reason`), `Reopen` (`reason` + optional `--to delivered --verify-by`), `Priority` when `priority-reason` is missing, `Force Unblock` (`reason`), `Record UC Validation` (`pass/fail/partial` + `summary`). | Small popover anchored to the button with a focused text input (`Enter` to apply, `Esc` to cancel). Zero full-screen modal. | Passes `--reason` + `--expect-task-hash`. Appends dated entry to `## Log` / `PROGRESS.md`. |
| **Level 2: Lightweight List Confirmation Dialog** | **Bulk actions** (`Validate & Close All (N)` on column header, `Close All Verified (N)`, `Pause All`), **Destructive actions** (`Withdraw Question`, `Discard Inbox Note`, `Delete Attachment`, `Cleanup Worktree`), and **Question Answering with Run Resume**. | Compact modal listing the affected `ID (short title)` items, an optional shared `Verification Note / Reason` input, and `[Confirm (N)]`. | Computes batch preview (`--dry-run`) and applies with `--expect-plan-hash`. |
| **Level 3: Full Diff Preview Modal (`ConfirmDialog`)** | **Multi-file / Structural / Config rewrites**: `Sync 00-INDEX.md`, `Use Cases adopt-links`, `Expand / Collapse` task folder, `Promote` microtask, `Accept Triage Proposal`, `Install Skills / Register MCP`, `Apply AGENTS.md`, `Orchestrator Reassign`. | Existing `ConfirmDialog` with unified diff, plan items, and `expect_plan_hash`. | Full `control-plane-safety.md` §2 plan hash + flock verification. |

### 3.5 The Owner as Verifier (`--verifier owner`) and Audit Trail

When the owner clicks **`Validate & Close`** (single or bulk) or **`Approve (Verified)`**:
1. **Command executed:** `ai-orch tasks transition <id> done --actor owner --verifier owner --owner-approved [--reason "<note>"] --expect-task-hash <hash>` (or `ai-orch tasks close <id> --actor owner --verifier owner --owner-approved [--reason "<note>"]`).
2. **Engine behavior (`T035`):**
   - If the task is in `delivered`, the engine walks `delivered -> verified -> done` in a single atomic transaction under `.ai-orch.lock`.
   - If the task is in `verified`, it transitions `verified -> done`.
   - Sets header `- verifier: owner` (satisfying the independent verification guard for all `verification-mode` values: `owner`, `independent-session`, `cross-agent`, `panel`, `self`).
   - Writes dated audit lines in `## Log` (for single-file tasks) or `PROGRESS.md` (for folder tasks) and in the `**Status:**` note of initiative tasks (`T067`):
     - `- 2026-10-27, owner: state delivered -> verified (verifier: owner) — Validated by owner from UI[: <optional note>]`
     - `- 2026-10-27, owner: state verified -> done (verifier: owner) — Validated by owner from UI[: <optional note>]`
   - Moves emergent task files to `tasks/done/<category>/` via `git mv` (or moves inline initiative blocks to `## Closed`).
   - Emits `task.state_changed` events (`delivered -> verified`, `verified -> done`) to `.ai-orchestration/events/`.
3. **Use-case regression guard (Spec 17 §5):** If the task is linked to an approved use case that is currently `failing` and has not passed a probe since the task was delivered, the engine refuses unless `--owner-approved` is set; in the UI, if a linked UC is `failing`, the button shows a warning badge `⚠ UC004 failing — Override & Close?` so the owner never overrides a failing use case accidentally.

### 3.6 Permissions: Direct Owner Actions vs. Contextual AI Chat

- **Direct UI Actions (Buttons, Inline Popovers, Bulk Actions):** Execute deterministically via `ai-orch` CLI with `--actor owner` (authenticated by the local UI token `X-AI-Orch-Token` or the VS Code extension host). They do not invoke an LLM and cost zero tokens.
- **Contextual AI Chat (`T074`):** Runs as a conversation turn with the AI session (the workspace's active interactive/headless orchestrator or a dedicated element session, see §6.1). As specified by the owner in `T074`, **the AI has all tools available (`ai-orch` CLI/MCP, file read/edit) and operates under its session's normal permission mode**—there is no artificial "read-only proposal-only" cage when the owner is chatting directly with their session.

---

## 4. Complete Action Matrix: Kanban Columns, States & Element Views (Clicks Today vs. Proposed)

### 4.1 Task Action Matrix by State & Surface (with Click-Count Comparison)

| State / Column | Action Name (Consistent English UI Label) | Surface Placement | Confirmation Level | Engine Command | Clicks Today (Web UI) | Clicks Proposed |
| --- | --- | --- | --- | --- | --- | --- |
| **All Visible States** (Any Card / Row / Detail) | **Change Priority** (`P0`–`P3`) | Clickable `[P1 ▾]` pill on Card, Queue, Tree, Timeline, Detail + Shortcut `p` | **Level 0** (Immediate + Toast Undo; inline reason input if required) | `set-priority <id> <P> [--reason <r>]` | **5 clicks** in Timeline (with diff modal); **Impossible** in Kanban / Queue / Tree / Detail | **2 clicks** (click pill -> click `P1`) or **2 keys** (`p` -> `2`) |
| **All Visible States** | **Change Executor** | Clickable `[@kilo ▾]` pill on Card, Queue, Tree, Detail + Shortcut `e` | **Level 0** (Immediate + Toast Undo) | `set-executor <id> <exec>` | **Impossible** (CLI only) | **2 clicks** (click pill -> pick executor) |
| **All Visible States** | **Change Size** (`XS`–`XL`) | Clickable `[M ▾]` pill on Queue, Tree, Timeline, Detail | **Level 0** (Immediate + Toast Undo) | `set-size <id> <size>` | **4 clicks** in Timeline (with diff modal); **Impossible** elsewhere | **2 clicks** |
| **All Visible States** | **Change Kind** (`feature`, `fix`, ...) | Clickable `[feature ▾]` badge on Card, Queue, Tree, Timeline, Detail | **Level 0** (Immediate + Toast Undo) | `set-kind <id> <kind>` | **Impossible** (no UI trigger) | **2 clicks** |
| **All Visible States** | **Link / Unlink Use Cases** (`UC###`) | Clickable `[UC001 +]` chip on Card, Queue, Tree, Detail + Shortcut `u` | **Level 0** (Immediate toggle in checklist popover + Toast Undo) | `link <id> <UC>` / `unlink <id> <UC>` | **Impossible** (planned in 17.10) | **2 clicks** (click chip -> toggle UC) |
| **All Visible States** | **Edit Labels** | Clickable `[+ tag]` chip on Card, Queue, Tree, Detail + Shortcut `l` | **Level 0** (Immediate toggle in popover + Toast Undo) | `set-labels <id> --add/--remove <lbl>` | **6 clicks** (open Detail -> Edit -> Modal -> Preview -> ConfirmDialog -> Apply) | **2 clicks** |
| **All Visible States** | **Toggle Next Up (`★`)** | Star icon `[☆]` / `[★]` on Card, Queue, Tree, Detail | **Level 0** (Immediate 1-click toggle) | `set-next-up <id> yes\|no` | **Impossible** (manual Markdown edit) | **1 click** |
| **All Visible States** | **Chat on Task (`💬`)** (`T074`) | `[💬]` icon on Card, Queue, Tree, Detail + Shortcut `c` | None (opens chat drawer / focuses input) | `orchestrator chat --about <id>` (or session relay) | **Impossible** (global chat only, manual ID typing) | **1 click** (or `c`) |
| **1. `open`** (Open Column / Queue / Tree) | **Start Task** (`-> in progress`) | Card quick button `[▶ Start]`, State pill, Detail footer | **Level 0** (Immediate + Toast Undo) | `transition <id> "in progress" --actor owner` | **2 clicks** for `NN.T` (open Detail -> Start); **Impossible** for `T###` without Run | **1 click** on card |
| **1. `open`** | **Run with Agent…** | Card button `[⚡ Run…]`, Detail footer | **Level 3** (`RunDialog` preview -> start) | `run start --task <id> ...` | **3–4 clicks** (open Detail -> Run… -> Start) | **2 clicks** from card |
| **1. `open` / `in progress`** | **Pause Task** (`-> paused`) | Card icon `[⏸]`, Queue row `[Pause]`, Detail footer, Column header `[⏸ Pause All]` | **Level 0** (Single: Immediate + Toast Undo) / **Level 2** (Bulk) | `transition <id> paused --actor owner` | **1 click** on Kanban/Queue (no hash/undo); **2 clicks** in Detail; **Impossible** in Tree | **1 click** everywhere (with hash + undo) |
| **2. `in progress`** (In Progress Column) | **Mark Delivered** (`-> delivered`) | Card quick button `[✓ Deliver]`, State pill, Detail footer | **Level 0** (Immediate; optional split-menu to set `verify-by`) | `transition <id> delivered --actor owner` | **2 clicks** (open Detail -> Mark Delivered, hidden if runs exist) | **1 click** on card |
| **3. `waiting` / `blocked`** (Waiting / Blocked Column) | **Answer Blocking Question** (`Q###`) | Card button `[💬 Answer Q011]` -> inline popover or Detail inline options | **Level 0/1** (Select option -> Answer) | `questions answer <Q###> --choice <c> --by owner` | **5+ clicks** (switch to Decisions tab -> find Q -> select -> Answer -> ConfirmDialog) | **2 clicks** inline from card or Task Detail |
| **3. `waiting` / `blocked`** | **Unblock Task** (`-> open` / `in progress`) | State pill / Card `[Unblock…]` | **Level 1** (Inline reason popover if `--force-unblock`) | `transition <id> open [--force-unblock --reason <r>]` | **Impossible** in UI | **2 clicks** |
| **4. `bounced`** (In Progress Column, Bounced badge) | **Resume / Re-run Executor** | Card button `[▶ Continue Run]` or `[▶ Start]` | **Level 0** (or `RunDialog` if new run) | `run continue <run_id>` or `transition <id> "in progress"` | **3–4 clicks** via Detail -> Runs panel | **1–2 clicks** on card |
| **5. `delivered`** (Delivered Sub-Column & Verification Queue) | **Validate & Close** (`delivered -> verified -> done`) (`T075`) | **Primary button `[✓✓ Validate & Close]`** on Card, Detail footer, Tree row, VS Code TreeView + Shortcut `v` | **Level 0** for single card (Immediate + Toast `[Add Note…] [Undo]`) or **Split-button `[▾]`** to add note before applying | `transition <id> done --actor owner --verifier owner --owner-approved [--reason <note>]` | **6 clicks + 2 modals** (Open Detail -> Approve -> closes modal -> Reopen Detail -> Close Task) | **1 click** (or key `v`) |
| **5. `delivered` (Bulk)** | **Validate & Close All (`N`)** (`T075`) | **Delivered Column Header** `[✓✓ Validate & Close (N)]` | **Level 2** (Compact dialog listing the `N` tasks + optional shared verification note) | Batch `transition <id> done --actor owner --verifier owner --owner-approved` | **Impossible** (6 × N clicks) | **2 clicks** (Header button -> Confirm) |
| **5. `delivered`** | **Approve Only (Mark Verified)** (`-> verified`) | State pill / Split-button `[▾]` -> `Mark Verified Only`, Detail footer | **Level 0** (Immediate + Toast Undo) | `transition <id> verified --actor owner --verifier owner --owner-approved` | **2 clicks** (Open Detail -> Approve) | **2 clicks** from card menu or **1 click** in Detail |
| **5. `delivered`** | **Bounce** (`-> bounced`) | Card button `[↩ Bounce]`, Detail footer | **Level 1** (Inline popover for `B1..Bn` findings) | `transition <id> bounced --actor owner --reason <r>` | **3 clicks** (Open Detail -> Bounce -> Confirm Bounce) | **2 clicks** on card |
| **5. `delivered`** | **Request Verification (`verify-by`)** | Clickable `[Verify-by: +]` pill on Card & Detail, Column header `[⊳ Request Verification…]` | **Level 0** (Pick workspace/session + optional check text) | `set-verify-by <id> <target> [--check <c>]` | **Impossible** (CLI only) | **2 clicks** |
| **6. `verified`** (Verified Sub-Column) | **Close Task** (`-> done`) | **Primary button `[✓ Close]`** on Card, Detail footer, Tree row | **Level 0** (Immediate + Toast Undo) | `transition <id> done --actor owner` | **2 clicks** (Open Detail -> Close Task) | **1 click** on card |
| **6. `verified` (Bulk)** | **Close All Verified (`N`)** | **Verified Sub-Column Header** `[✓ Close All (N)]` | **Level 2** (Compact dialog listing the `N` verified tasks) | `close --verified --expect-plan-hash <h>` | **Impossible** (2 × N clicks) | **2 clicks** |
| **7. `paused`** (Paused Column) | **Resume Task** (`-> open` or prior state) | Card button `[▶ Resume]`, Column header `[▶ Resume All (N)]` | **Level 0** (Single) / **Level 2** (Bulk) | `transition <id> open --actor owner` | **1 click** on card; **Impossible** in bulk | **1 click** (Single) / **2 clicks** (Bulk) |
| **8. `done` / `done with a caveat` / `dropped`** (Done / Dropped Columns & Tree) | **Reopen Task** (`-> open` or `-> delivered`) | Card button `[↺ Reopen]`, Tree row, Detail footer | **Level 1** (Inline popover: target `open` vs `delivered`, optional `verify-by`, mandatory `reason`) | `reopen <id> --to open\|delivered [--verify-by <t>] --reason <r>` | **4 clicks** in Tree only (`open` target only); **Impossible** in Kanban/Detail or to `delivered` | **2 clicks** everywhere |
| **Any Non-Terminal Leaf** | **Drop Task** (`-> dropped`) | Card `[⋯]` menu -> `Drop Task…`, State pill, Detail footer | **Level 1** (Popover requiring drop `reason`) | `transition <id> dropped --actor owner --reason <r>` | **Impossible** in UI | **2 clicks** |

### 4.2 Element View Action Matrix (Use Cases, Questions, Inbox Notes)

| Element View | Action Name (English UI Label) | Surface Placement | Confirmation Level | Engine Command | Clicks Today | Clicks Proposed |
| --- | --- | --- | --- | --- | --- | --- |
| **Use Cases** (`UseCasesManager` & `UseCaseDetailModal`) | **Approve / Set Approval** (`proposed` / `approved` / `deprecated`) | Clickable `[PROPOSED ▾]` badge on UC card & Detail header | **Level 0** (Immediate + Toast Undo) | `use-cases set-approval <UC> <val>` | **Impossible** | **2 clicks** (or 1-click `[✓ Approve]` on `proposed` card) |
| **Use Cases** | **Validate with AI** (run probe) | Card button `[▶ Validate]`, Detail footer, VS Code TreeView inline button | **Level 0** (Immediate run; if stage != ready, offers `[Force Validate]`) | `use-cases validate <UC> [--force]` | **1 click** (uses `alert()` on error) | **1 click** (in-app toast/banner, no `alert()`) |
| **Use Cases** | **Record Owner Verdict** (`Pass` / `Fail` / `Partial`) | Card `[⋯]` menu & Detail header `[✓ Record Verdict…]` | **Level 1** (Popover: `Pass` \| `Fail` \| `Partial` + 1-line summary) | `use-cases record-validation <UC> --verdict <v> --summary <s> --actor owner` | **Impossible** (CLI only) | **2 clicks** |
| **Use Cases** | **Create Task from Use Case** | Card `[+ Task]` button & Detail `Linked Tasks` header `[+ New Task from UC]` | **Level 1/2** (Pre-filled modal from UC title, steps, criteria) | `tasks new --from-use-case <UC> ...` | **Impossible** | **2 clicks** |
| **Use Cases** | **Link / Unlink Existing Task** | Detail & Card `[+ Link Task ▾]` popover; click task pill to open task, `×` to unlink | **Level 0** (Immediate + Toast Undo) | `tasks link <task> <UC>` / `unlink` | **Impossible** (pills are static text) | **1 click** to open task; **2 clicks** to link/unlink |
| **Use Cases** | **Edit Use Case** (title, actor, priority, scenario, command) | Detail `[✎ Edit]` toggle + inline priority/actor pills | **Level 0** (Inline save with hash) | `use-cases create --id <UC> ...` (preserving validation log!) | **Impossible** in UI | **2 clicks** |
| **Use Cases** | **Chat on Use Case (`💬`)** (`T074`) | Card `[💬]` & Detail chat drawer | None | Scoped chat turn on `UC###` | **Impossible** | **1 click** |
| **Questions** (`DecisionsTab` & `TaskDetailModal`) | **Answer Question** (pick option) | Option row in `DecisionsTab` AND inline inside `TaskDetailModal`; `[✓ Answer]` | **Level 0** (1-click on `[Answer A (Recommended)]` or select + `Answer` with Toast Undo; checkbox `[x] Mark applied` & `[ ] Changes finished task result`) | `questions answer <Q###> --choice <c> --by owner [--apply-ref <r>] [--changes-result]` | **3 clicks** in DecisionsTab (always opens `ConfirmDialog`); **Impossible** inside `TaskDetailModal` | **1–2 clicks** in both DecisionsTab and `TaskDetailModal` |
| **Questions** | **Mark Decision Applied** | `Awaiting Application` card `[✓ Mark Applied]` (1-click with default blocked task ref, or popover for custom ref) | **Level 0** (1-click default ref) / **Level 1** (custom ref) | `questions apply <Q###> --by owner --ref <ref>` | **3 clicks** (opens modal every time) | **1 click** |
| **Questions** | **Move to External Tracker** | Question card `[⋯]` -> `Move to Tracker…` | **Level 1** (Popover for tracker URL + optional reason) | `questions move <Q###> --to <url>` | **Impossible** (CLI only) | **2 clicks** |
| **Questions** | **Chat on Question (`💬`)** (`T074`) | `[💬 Discuss with AI]` on Question card | None | Scoped chat turn on `Q###` | **Impossible** | **1 click** |
| **Inbox Notes** (`InboxPanel` & `NoteEditorModal`) | **Quick Convert to Task / Microtask / Use Case** | Row hover buttons `[+ Task]`, `[⚡ Micro]`, `[+ UC]` + inside `NoteEditorModal` | **Level 0** for `[⚡ Micro]` (1 click!); **Level 1** modal for Task / UC | `inboxToMicrotask` / `inboxToTask` / `use-cases create` + `inbox resolve` | **3–4 clicks** (must open `NoteEditorModal` first) | **1 click** (`⚡ Micro`) / **2 clicks** (`+ Task` / `+ UC`) from row |
| **Inbox Notes** | **Quick Discard / Resolve** | Row hover `[✓ Resolve]` `[🗑 Discard]` + Bulk selection bar | **Level 1** (Inline reason popover) / **Level 2** (Bulk) | `inbox resolve` / `inbox discard` | **3–4 clicks** inside modal only | **2 clicks** from row |

---

## 5. ASCII Mockups

### 5.1 Kanban Column Headers & Card Quick Actions + Inline Edit Popovers

```text
+----------------------------------------------------------------------------------------------------------------------+
| WORKFLOW BOARD                                      [☆ Next-up only] [⏸ Show paused (2)] [👁 Show done (68)] [Sync] |
+======================================================+===============================================================+
| ● IN PROGRESS (3)                        [⏸ Pause 3] | ● DELIVERED / VERIFIED (4)                                    |
+------------------------------------------------------+---------------------------------------------------------------+
| +--------------------------------------------------+ | Delivered — needs verification (3)  [✓✓ Validate & Close (3)] |
| | [P1 ▾] [⚙ engine ▾] [M ▾]          [☆] [⏸] T070 | |                                     [⊳ Verify-by…           ] |
| | orchestrator reassign binds interactive session  | | +-----------------------------------------------------------+ |
| | [UC028 ×] [UC038 ×] [+ UC]  [#session ×] [+ tag] | | | [P1 ▾] [📐 method ▾] [M ▾]            [★] [💬] [⋯]  T073 | |
| | [@kilo ▾]              [💬 Chat] [✓ Deliver ▾]   | | | Study: cross-workspace orchestrator control plane         | |
| +--------------------------------------------------+ | | [UC028] [UC039] [+ UC]   Verify-by: [owner ▾]             | |
|          |                                           | | [@kilo ▾]    [↩ Bounce…]  [✓✓ Validate & Close ▾]         | |
|          v  (Clicking [P1 ▾] opens inline popover)   | +-----------------------------------------------------------+ |
|   +--------------------------------------+           |                                      |                        |
|   | Set Priority for T070          [Esc] |           |   (Clicking [✓✓ Validate & Close] applies in 1 click!         |
|   | [P0]  [*P1*]  [P2]  [P3]             |           |    Clicking [▾] opens optional note/verdict menu:)            |
|   | Reason: [Requested by owner N068___] |           |   +-------------------------------------------------------+   |
|   | (Click P0-P3 or press Enter -> saves |           |   | ✓✓ Validate & Close now (verifier: owner)        [v] |   |
|   |  immediately with hash + Undo toast) |           |   | ✓✓ Validate & Close with note…                       |   |
|   +--------------------------------------+           |   | ✓  Approve only (move to Verified, keep open)        |   |
|                                                      |   | ⚠  Close with caveat (self-verified / note)…         |   |
|                                                      |   +-------------------------------------------------------+   |
|                                                      | - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - |
|                                                      | Verified — ready to close (1)            [✓ Close All (1)]    |
|                                                      | +-----------------------------------------------------------+ |
|                                                      | | [P2 ▾] [🔧 fix ▾] [S ▾]   Verifier: owner     [💬]  T069 | |
|                                                      | | Validation campaign skips draft use cases                 | |
|                                                      | | [@kilo ▾]                     [↩ Reopen]  [✓ Close]       | |
|                                                      | +-----------------------------------------------------------+ |
+======================================================+===============================================================+
| Bottom-right Toast after 1-click Validate & Close:                                                                   |
| +------------------------------------------------------------------------------------------------------------------+ |
| | ✓ T073 (Studio pannello orchestratori) validated & closed by owner.                  [+ Add Note]  [Undo (5s)]   | |
| +------------------------------------------------------------------------------------------------------------------+ |
+----------------------------------------------------------------------------------------------------------------------+
```

### 5.2 Bulk "Validate & Close" Confirmation Dialog (`T075` — Level 2 Confirmation)

```text
+==============================================================================+
| ✓✓ Validate & Close 3 Delivered Tasks                                    [×] |
+------------------------------------------------------------------------------+
| The following 3 visible tasks in Delivered will be marked `verified`         |
| (`verifier: owner`) and closed (`done`, moved to `tasks/done/`):             |
|                                                                              |
|  [x] T073 (Studio pannello orchestratori) — Study: orchestrator control...   |
|  [x] T075 (Valida e chiudi da UI) — Validate & close button on Delivered...  |
|  [x] 16.9b (Web UI multi-project) — Switcher, project and common views       |
|                                                                              |
| Validation Note (optional, recorded in each task's ## Log / PROGRESS.md):    |
| +--------------------------------------------------------------------------+ |
| | Validated live in the UI by owner.                                       | |
| +--------------------------------------------------------------------------+ |
|                                                                              |
| [Cancel]                                    [✓✓ Validate & Close 3 Tasks]    |
+==============================================================================+
```

### 5.3 Task Detail Modal: Inline Header Bar, Interactive Steps, Inline Questions & Contextual AI Chat (`T074`)

```text
+======================================================================================================================+
| Initiatives / 17 / 17.5                                                                                          [×] |
| [P1 ▾] [ai-orch] 17.5 (Stadio degli use case ✎) [✨ feature ▾] [M ▾] [State: waiting ▾] [★ Next-up]                  |
| Ciclo di vita: approvazione e stadio derivato                                                                        |
+----------------------------------------------------------------------------------------------------------------------+
| Executor: [@kilo ▾]  | Profile: [bulk-execution ▾] | Verify-by: [owner ▾]        | Use Cases: [UC012 ×] [+ Link UC▾] |
| Mode: [owner ▾]      | Depends on: [17.1 ×] [+ ▾]  | Labels: [#ui ×] [#uc ×] [+] | File: tasks/17-.../plan.md [Open] |
+======================================================================================================================+
| [📄 Specification & Steps]  [⚡ Runs (1)]  [📎 Attachments (0)]         [Structured | Raw]   [💬 Contextual Chat (2)] |
+----------------------------------------------------------------------+-----------------------------------------------+
| ## Goal                                                              | 💬 CHAT ON 17.5 (Stadio degli use case)       |
| Spec §3 according to Q011: `approval` field with migration from      | Context: 17.5 + spec/use-cases-drive-tasks.md |
| `status`, `stage` as pure function; shown by show/list/index.        | + Q011 + UC012 · Session: ai-coding-tools-d8  |
|                                                                      | --------------------------------------------- |
| ## Steps  (Click checkbox to toggle in place via `tasks step check`) | [Owner 15:02]: Can we also include `partial`  |
| - [x] 1. Parse `approval:` header and fallback from legacy `status:` | in the migration from status to last-verdict? |
| - [ ] 2. Implement pure `compute_use_case_stage(uc, linked_tasks)`   |                                               |
| - [ ] 3. Expose `approval` and `stage` in `use-cases list/show`      | [Claude 15:02]: Yes — I updated step 1 of     |
| [+ Add step…_______________________________________________] [Add]   | `17.5` and §3 of `use-cases-drive-tasks.md`   |
|                                                                      | so `partial` maps to `approval: approved` and |
| ## Blocking Questions (1 Open — Answer directly here!)               | `last-verdict: partial`.                      |
| +------------------------------------------------------------------+ |   ✓ Edited tasks/specs/use-cases-drive-...    |
| | Q011 (Approvazione vs stadio UC) · Open · Blocks: 17.5           | |   ✓ Edited tasks/17-use-cases-drive-tasks/... |
| | Separiamo l'approvazione di uno use case dal suo stadio derivato?| |                                               |
| | (o) A — Sì: campo `approval` + `stage` derivato [Recommended]    | | [Ask or instruct AI on 17.5…                ] |
| | ( ) B — No: un solo campo con `draft (approved)`                 | | [____________________________________] [Send] |
| | Note: [________________________________________________________] | +-----------------------------------------------+
| | [x] Mark applied to 17.5   [Withdraw…]     [✓ Answer & Unblock]  |
| +------------------------------------------------------------------+ |
+======================================================================================================================+
| State: waiting (blocked by Q011)     [⏸ Pause] [🔓 Force Unblock…] [⚡ Run…] [✓ Deliver] [✓✓ Validate & Close ▾]     |
+======================================================================================================================+
```

### 5.4 Use Case Detail Modal & Card Quick Actions

```text
+======================================================================================================================+
| [UC012] (Use case lifecycle ✎)  [Approval: APPROVED ▾]  [Stage: IN DEVELOPMENT (2/4 tasks done)]  [P1 ▾]  Actor: [Owner ▾] [×] |
| Owner manages use case approval and derived readiness stage                                                          |
+----------------------------------------------------------------------------------------------------------------------+
| Verification Type: [automated-probe ▾] | Last Tested: 2026-10-27 (PASS) | Revalidation: [pending ⚠] | [✎ Edit UC]   |
+======================================================================================================================+
| LINKED IMPLEMENTATION TASKS (2/4 done — Click any task to open, or change its state/priority inline!)                |
| +------------------------------------------------------------------------------------------------------------------+ |
| | ✓ 17.1 (Proiezione collegamenti) [P1 ▾] [done]          | ⏳ 17.5 (Stadio degli use case) [P1 ▾] [waiting Q011]   | |
| | ✓ 17.2 (Link e riscrittura)      [P1 ▾] [verified] [✓]  | ○ 17.6 (Validazione se pronti) [P2 ▾] [open] [▶ Start]| |
| +------------------------------------------------------------------------------------------------------------------+ |
| [+ Create New Task from UC012…]   [+ Link Existing Task ▾]                                                           |
|                                                                                                                      |
| ## Scenario / Interaction Steps                                                                                      |
| 1. Owner creates a use case (`approval: proposed`, `stage: draft`).                                                  |
| 2. Owner clicks `[✓ Approve]` on the use case card (`approval: approved`).                                           |
| 3. Owner clicks `[+ Create Task from UC]` -> task is created with `--use-case UC012` (`stage: planned`).             |
|                                                                                                                      |
| ## 💬 Contextual AI Chat on UC012                                                                                    |
| [e.g. "Split step 3 into two acceptance criteria and create the backend task"______________________________] [Send]  |
+======================================================================================================================+
| tasks/use-cases/UC012-lifecycle.md    [✓ Record Manual Verdict ▾]  [▶ Force Validate with AI]  [✓ Approve Use Case]  |
+======================================================================================================================+
```

### 5.5 Question Detail / Card in `DecisionsTab` (with 1-Click Recommended Answer, Move to Tracker & Contextual AI Chat)

```text
+======================================================================================================================+
| [Q011] (Approvazione vs stadio UC ✎)  [Open]  Asked by: claude (today)             Blocks: [→ 17.5 (Stadio UC)] [⋯] |
| Separiamo l'approvazione di uno use case dal suo stadio derivato dai task?                                           |
+----------------------------------------------------------------------------------------------------------------------+
| ▸ Context & Background (click to expand)                                                                             |
|                                                                                                                      |
| Answer Options:                                                                                                      |
|  (o) A — Sì: campo `approval` (proposed|approved|deprecated) + `stage` derivato dai task  [★ Recommended]           |
|  ( ) B — No: un solo campo con valore `draft (approved)`                                                             |
|  ( ) Other / open answer: [Optional note or custom answer…_________________________________________________________] |
|                                                                                                                      |
| 💬 Discuss Q011 with AI: ["What happens to existing verified UCs under Option A?"_________________________] [Ask AI] |
+----------------------------------------------------------------------------------------------------------------------+
| [Withdraw…]  [↗ Move to Tracker…]         [x] Record as applied (`--apply-ref 17.5`)    [✓ Answer A (Recommended)]   |
+======================================================================================================================+
```

---

## 6. How T074 and T075 Fit & Unified Implementation Plan

### 6.1 How `T075` (Validate & Close) and `T074` (Contextual AI Chat) Fit into the Architecture

1. **`T075` (Validate & Close from UI) is the flagship transition action of this model:**
   - Rather than a one-off button, `T075` is implemented via a unified **Single & Batch Transition Endpoint** (`POST /api/tasks/validate-close` + `/preview`, or extending `/api/tasks/transition` and `/api/tasks/close`) that accepts `{ task_ids: string[], reason?: string, expect_hashes?: Record<string, string>, expect_plan_hash?: string }`.
   - On a **single card** (`Delivered` or `Verified`) or in **`TaskDetailModal`**, clicking `[✓✓ Validate & Close]` (or pressing `v`) executes immediately (Level 0 confirmation) with `--actor owner --verifier owner --owner-approved`, showing the undo/add-note toast. Clicking the split caret `[▾]` lets the owner type a verification note first.
   - On the **`Delivered` and `Verified` column headers**, clicking `[✓✓ Validate & Close (N)]` opens the Level 2 checklist dialog (Mockup §5.2) with a shared optional note and applies across all checked tasks.
2. **`T074` (Contextual AI Chat per Element) is the universal AI escape hatch for any interaction:**
   - Whenever an owner interaction goes beyond a 1-click field change—e.g. *"rewrite the steps of T075"*, *"split UC012 into two tasks"*, *"what are the trade-offs of Q011?"*—the owner clicks `[💬]` (or presses `c`) on that Task, Use Case, Question, or Inbox Note.
   - **Data Model:** Every turn in `orchestrator/queue/` and `conversation` gains an optional `context_ref: { kind: "task" | "use_case" | "question" | "note", id: string, project: string }` (stored as `about: "T076"` / `thread_id: "element:ai-orchestration/T076"`).
   - **Context Assembly:** On the first turn (or when the element file's SHA256 has changed since the last turn in that element's thread), the backend automatically prepends a compact `<element_context>` block containing the element's Markdown file, its linked use cases / tasks / questions summaries, and its latest run/validation status.
   - **Full Tool Access:** The responding AI session (per `T073`, either the workspace's active interactive/headless orchestrator session or a dedicated session resumed per element) has **all standard tools** (`ai-orch` CLI/MCP, file edits) under its session permission mode. Any mutation it performs emits standard events and updates the open modal/card live via WebSocket.
   - **Dual Visibility:** Each element's chat history is persisted per element (shown inside `TaskDetailModal` / `UseCaseDetailModal` / `DecisionsTab` / slide-over drawer) **and** appears in the main `OrchestratorChatPanel` tagged with a clickable `[T076 (Studio interazioni UI)]` chip (filterable by element).

### 6.2 Proposed Initiative Breakdown (Backend, Web UI, and VS Code Extension Separated)

We recommend organizing this work into a dedicated initiative (e.g., **Initiative 18 — Fast Owner Interactions, Inline Editing & Contextual Element Chat**, absorbing `T075` and `T074` and coordinating with Initiative `17`'s `17.9`–`17.10`):

| Task ID | Layer | Title & Scope | Size | Depends On | Priority |
| --- | --- | --- | --- | --- | --- |
| **18.1** (`T075` backend) | **Engine & Backend** | **Validate & Close (`validate-close`) single/bulk + missing task mutation endpoints** — Add `set-next-up <id> yes\|no` to `tasks_engine.py`; add backend endpoints in `server.py` for single & bulk `validate-close` (`transition <id> done --verifier owner --owner-approved`), `close --verified`, `set-executor`, `set-verify-by`, `verification-queue`, `set-waiting-on`, `set-next-up`, `step check/uncheck/add`, `move --to-project`, `ship`, and `reopen --to delivered --verify-by`. Standardize `--actor owner`. | M | - | **P1** (Immediate) |
| **18.2** (`T075` UI + ext) | **Web UI & VS Code** | **Validate & Close buttons on Delivered/Verified columns, cards, detail, and VS Code TreeView** — Add 1-click `[✓✓ Validate & Close]` (with split-button note option & toast undo) on `Delivered`/`Verified` cards, Tree rows, and `TaskDetailModal`; add bulk `[✓✓ Validate & Close (N)]` on Kanban column headers with checklist + note dialog; add bridge handlers in `dashboard-panel.ts` and context-menu commands in VS Code `nextUpView`/`initiativesView`. | M | 18.1 | **P1** (Immediate) |
| **18.3** | **Web UI** | **Universal `<InlineFieldPopover>` & Silent Preview-Hash-Apply with Toast Undo** — Build reusable inline-edit popover + undo toast system. Make `Priority`, `State` (allowed transitions only), `Executor`, `Size`, `Kind`, `Verify-by`, `Labels`, `Use Cases`, and `Next-up ★` clickable in place across Kanban cards, Queue rows, Tree rows, Timeline cards (removing the full-screen diff modal for single-field edits in Timeline!), and `TaskDetailModal`. Include inline reason input when required (`priority-reason`, `bounced`, `dropped`, `reopen`). | L | 18.1, 17.2 | **P1** |
| **18.4** | **Engine & Backend** | **Use Case, Question & Inbox quick-action endpoints** — Add `use-cases record-validation`, `use-cases edit` (header/body update preserving validation log), `questions move`, `questions answer --changes-result --apply-ref`, and `inbox to-use-case` endpoints in `server.py`. | S | 17.5 | **P1** |
| **18.5** | **Web UI** | **Interactive Detail & Cross-Navigation for Tasks, Use Cases, Questions, and Inbox** — Make `## Steps` checkboxes interactive in `TaskDetailModal`; allow answering blocking `Q###` questions inline inside `TaskDetailModal`; make all `Task T###` and `UC###` pills clickable across views; add `Record Verdict`, `Approve`, `Edit`, and `+ Task from UC` to `UseCasesManager`/`UseCaseDetailModal`; add 1-click `Answer Recommended`, `Move to Tracker`, and `moved` filter to `DecisionsTab`; add row-level quick actions to `InboxPanel`. Replace remaining `window.alert`/`window.confirm` calls. | M | 18.3, 18.4 | **P2** |
| **18.6** (`T074` spec + backend) | **Engine & Backend** | **Contextual Element Chat (`T074`) backend & context assembler** — Finalize `tasks/specs/contextual-element-chat.md`; add `element_ref` (`task` \| `use_case` \| `question` \| `note`) to chat turns/threads; build automatic `<element_context>` assembler (element file + linked UCs/tasks/questions/logs); route turns to workspace orchestrator or per-element session with full tool access. | M | T073 | **P1** |
| **18.7** (`T074` UI + ext) | **Web UI & VS Code** | **Contextual Element Chat UI (`T074`)** — Add `[💬]` button on every card/row and persistent Contextual Chat drawer/pane in `TaskDetailModal`, `UseCaseDetailModal`, `DecisionsTab`, and `InboxPanel`; show element-tagged turns in `OrchestratorChatPanel` with filter chips; sync to VS Code webview. | M | 18.6 | **P1** |
| **18.8** | **Web UI & VS Code** | **Keyboard Shortcuts & VS Code Sidebar TreeView Context Menus** — Add keyboard navigation (`v`, `p`, `e`, `s`, `l`, `u`, `c`, `Space`) on boards/lists and add full right-click context menu commands (`Validate & Close`, `Pause/Resume`, `Set Priority`, `Set Executor`, `Validate Use Case`, `Answer Question`, `Chat on Element`) to VS Code sidebar tree views. | S | 18.2, 18.3, 18.7 | **P2** |

---

## 7. Open Questions for the Owner

### Q-A: Single-Click "Validate & Close" Confirmation vs. Always Showing a Dialog (`T075`)
- **Context:** In `T075`, the initial description mentioned a confirmation dialog with the task list and an optional note, while the owner's `T076` addendum specifies: *"Frequent actions cost one click from where the element is shown... Confirmation only for destructive or bulk actions; everything else applies immediately with a quick undo."*
- **Options:**
  - **Option A (1-Click Immediate on Single Card + Toast with `[+ Add Note]` & `[Undo]`; Dialog only for Bulk Column Header — Recommended):** Clicking `[✓✓ Validate & Close]` on a single card or detail modal validates and closes it immediately in **1 click**, showing a toast `✓ T075 validated & closed [Add Note…] [Undo]` (plus a split-button caret `[▾]` on the button if the owner wants to type a note beforehand). Clicking `[✓✓ Validate & Close All (N)]` on the **column header** opens the confirmation dialog with the list of `N` tasks and optional note.
  - **Option B (Always Open Confirmation Dialog for Both Single and Bulk):** Even a single-card `Validate & Close` opens a confirmation modal asking for an optional note (2 clicks minimum).
- **Recommendation:** **Option A**. It satisfies the 1-click speed criterion for single tasks while still giving a 1-click path to add a note (via split-button `[▾]` or toast) and keeping the confirmation dialog for bulk column operations.

### Q-B: `priority-reason` When Changing Priority Inline
- **Context:** The task grammar requires `priority-reason` to be non-empty on full emergent tasks (`T###`), whereas microtasks and initiative tasks (`NN.T`) do not require it. When the owner clicks `[P2 ▾]` on an emergent task card and picks `P1`:
- **Options:**
  - **Option A (1-Click Apply Keeping/Updating Reason Optional, Prompt Only if Empty — Recommended):** Selecting `P0`–`P3` in the popover applies **immediately in 1 click** if the task already has a `priority-reason` (while also showing an optional inline `Reason` input in the popover if the owner wants to type a new reason first, or `[Edit reason]` in the toast). If the task has no `priority-reason` (`-`), the inline input is focused and `Enter` applies.
  - **Option B (Always Require Typing a New `priority-reason` Before Applying):** Every priority change on an emergent task requires typing a new reason and pressing `Enter` (2 steps instead of 1 click).
- **Recommendation:** **Option A**. Most tasks created by `tasks new` or triage already have a `priority-reason`; forcing the owner to re-type a reason every time they bump `P2 -> P1` on the board slows down triage.

### Q-C: Who Responds to Contextual Element Chat (`T074`)?
- **Context:** When the owner opens Contextual Chat on `T076`, `UC012`, or `Q011` and sends a message:
- **Options:**
  - **Option A (Dedicated Per-Element Resumable Session, with Option to Route to Workspace Orchestrator — Recommended):** Default to a lightweight resumable session bound to the element (`element:<project>/<id>`, using the configured `orchestration` or `deep-reasoning` profile and `--resume <session_id>` on subsequent turns on that same element) so the conversation stays 100% focused on that element and can run in parallel without blocking or polluting the main workspace orchestrator's context window; include a toggle in the chat header `[Responder: Element Session ▾ | Workspace Orchestrator]`.
  - **Option B (Always Route Through the Single Workspace Orchestrator Queue):** Every contextual element chat turn is enqueued into the workspace orchestrator's single turn queue (`owner_chat` with `<element_context>`).
- **Recommendation:** **Option A**. If the owner is discussing `UC012` while the main orchestrator is busy running a turn or if the owner chats on 3 different tasks, a per-element session responds immediately, keeps a clean element-specific context, and still has all `ai-orch` and file tools.

### Q-D: Clicking a Task or Use Case in the VS Code Sidebar TreeViews
- **Context:** Today in the VS Code extension sidebar (`Next Up`, `Initiatives`, `Use Cases`), clicking a task or use case opens its raw `.md` file in the text editor (`vscode.open`), whereas clicking a question in `Decisions Waiting` opens the Dashboard Webview focused on that question.
- **Options:**
  - **Option A (Open Item Detail in Dashboard Webview on Click; Keep `Open Markdown File` as Inline Action Icon — Recommended):** Clicking a task, initiative, or use case in the VS Code sidebar opens its interactive Detail Modal in the AI Orchestration Dashboard (where inline edits, `Validate & Close`, and Contextual Chat live), while the inline `[$(go-to-file)]` icon on the tree row opens the raw `.md` file in the editor.
  - **Option B (Keep Click = Open Raw `.md` File; Add `Open in Dashboard` Inline Icon):** Preserve current behavior.
- **Recommendation:** **Option A**, so the VS Code sidebar and Dashboard act as one cohesive UI rather than dropping the owner into raw Markdown when they click a task.
