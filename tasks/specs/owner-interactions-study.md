# Study: Owner Interactions with Registry Elements from the UI (T076)

- **Task:** `T076 (Studio interazioni UI)`
- **Date:** 2026-10-27 (revised after independent Codex review)
- **Status:** Revised draft for owner review
- **Scope:** `ai-orchestration` (`tasks_engine.py`), `ai-orchestration-ui` (`backend/server.py`, `frontend/src/components/*`), `vscode-ai-orchestration` (`src/*`, webview bridge & native sidebar tree views)
- **Related specs & tasks:** `T074 (Chat contestuale per elemento)` (`tasks/specs/contextual-element-chat.md`), `T075 (Valida e chiudi da UI)`, `T073 (Studio pannello orchestratori)`, Initiative `17` (`use-cases-drive-tasks.md`), `task-and-state-model.md`, `control-plane-safety.md`, `ui-multi-project.md`, `orchestration-extension-spec.md`.

---

## Executive Summary & Guiding Principles

The owner has requested several high-frequency UI interactions over recent sessions:
- *"Validate & close"* on the `Delivered` column header and on individual tasks (`T075`);
- *Contextual AI chat* inside a task, use case, question, or inbox note view (`T074`, where the AI has full tool access and only the conversation context is scoped to the element);
- *Inline field editing* (2026-10-27: *"e.g. interface to change priority: clicking the current priority opens a menu to change it"*);
- *Process inbox* (2026-10-27: *"mi processi tutti gli inbox? anche per questo servirebbe un comando sull'interfaccia, che eventualmente apre una chat"*);
- Earlier requests: quick *Pause / Resume* buttons on cards, *Request validation* (`verify-by`), and *Show/hide empty projects*.

Designing these piece by piece has left an inconsistent interaction model:
- Changing a task's priority works only in the Timeline view and requires **4 clicks** (+ optional typing): (1) click priority pill (`TimelineCard.tsx:491`), (2) click `P0`–`P3` in the popover (`TimelineCard.tsx:526`), (3) click `Preview` (`TimelineCard.tsx:582`), (4) click `Apply` in the full-screen `ConfirmDialog` diff modal (`TimelineView.tsx:330-350`).
- Validating & closing a delivered task today requires **4 clicks across two modal openings**: (1) click the `delivered` card to open `TaskDetailModal`, (2) click `Approve (Verified)` (`TaskDetailModal.tsx:2333`), which calls `onClose()` (`TaskDetailModal.tsx:715`), (3) click the card again in the `Verified` sub-column to reopen `TaskDetailModal`, (4) click `Close Task (Done)` (`TaskDetailModal.tsx:2356`)—whereas the CLI engine (`T035`) already supports a single `transition <id> done --verifier owner` walk.

### Guiding Criterion: Speed ("Interagire Velocemente")
1. **Minimal clicks from where the element is seen (no view switching):**
   - **Direct primary action buttons** on a card or row (`Validate & Close`, `Pause / Resume`, `Start`, `Deliver`, `Chat`, `Process Note`) cost **1 click**.
   - **Inline field popover edits** (`Priority`, `Executor`, `State` transitions, `Size`, `Kind`, `Verify-by`, `Use Cases`, `Labels`) cost **2 clicks** (1 click to open the pill menu -> 1 click to select the valid value; + `Enter` only when a mandatory reason is missing).
   - **Keyboard shortcuts** cost **1 key** (`v`, `p`, `e`, `s`, `l`, `u`, `c`, `Space`) when a card, row, or detail modal already has focus.
2. **Restrained Card Density (1–2 Primary Actions + 1 Overflow Menu `[⋯]`):**
   - To avoid cramming 8 tiny buttons onto a Kanban card, each card renders **only its core identity/metadata pills** (`Priority`, `Kind`, `Executor`, `Use Cases`), **1–2 state-specific primary actions** (e.g. `[✓✓ Validate & Close]` and `[💬]` on `delivered`), and **one consistent overflow/context menu `[⋯]`** (also triggered by right-click) holding secondary transitions (`Bounce…`, `Verify-by…`, `Reopen…`, `Drop…`, `Move to Project…`, `Copy Handoff`).
3. **VS Code Sidebar TreeViews vs. React Webview:**
   - VS Code's native `TreeView` (`nextUpView`, `initiativesView`, `decisionsView`, `useCasesView`) **cannot render React inline-edit pills or custom HTML popovers**. Its fast path consists of **inline action icons** (`"group": "inline"` in `package.json`, up to 2–3 icons on hover such as `Validate & Close`, `Chat on Element`, `Open Markdown File`), **rich right-click context menus** (`view/item/context` with QuickPick for `Set Priority`, `Set Executor`, `Transition State`), and **keybindings** (`when: "focusedView == nextUpView"`). Clicking a tree item opens its interactive Detail Modal in the Dashboard Webview.
4. **Honest Reversibility (Exact Inverse `[Undo]` vs. Compensating `[Reopen]`):**
   - Single-item field edits with an **exact inverse** (`priority`, `size`, `kind`, `executor`, `labels`, `use-cases`, `short`, `next-up`, `verify-by`, `step check/uncheck`, `UC approval`) apply immediately and show a toast with **`[Undo]`**, which re-applies the previous value against the **new post-mutation `task_hash`**.
   - State closures (`Validate & Close`, `Close`) have **no exact inverse** (since `git mv` archives the file and appends audit log lines); their toast offers a compensating **`[Reopen]`** button (`tasks reopen <id> --to delivered`). Transitions with no clean inverse (`open -> in progress`, `delivered -> verified`, `questions answer`, `questions apply`, `use-cases record-validation`) do not show a fake `[Undo]` button.

---

## 1. Inventory: Engine Actions, Entity Capabilities & UI/Extension Coverage

### 1.1 Per-Entity Capability Matrix (Full Task vs. Microtask vs. Initiative Leaf vs. Container)

Not every task node supports the same fields or commands in `tasks_engine.py`. The UI must only expose controls that are valid for that entity subtype:

| Capability / Field | Emergent Full Task (`tasks/<cat>/T###-*.md` or `T###-*/README.md`) | Microtask (`tasks/micro/T###-*.md`) | Initiative Leaf Task (`NN.T` in `tasks/NN-slug/plan.md`) | Initiative / Parent Container (`NN` or `NN.T` with children) |
| --- | --- | --- | --- | --- |
| **State (`state`)** | Own state (`open`..`done`, `dropped`, `paused`) | Own state (`open`..`done`, `dropped`, `paused`) | Own state (`open`..`done`, `dropped`, `paused`) | **Derived from descendants (`compute_derived_state`) — NO state pill or transition buttons! Only `ship <NN>` when all leaves are `done`.** |
| **Priority (`P0`–`P3`)** | Own (`priority` + **mandatory `priority-reason`**) | Own (`priority`; `priority-reason` optional) | Own (`**Priority:**` override) or inherited from initiative | Own (`Priority` column in `00-INDEX.md` initiatives table) |
| **Size (`XS`–`XL`)** | Optional header `- size:` | Fixed `XS` (weight `0.5`; use `promote` to resize) | Own (`**Size:**`) | Own (`Size` column in `00-INDEX.md`) |
| **Kind (`feature`, `bug`, ...)** | Own (`- kind:`) | Own (`- kind:`, required at creation) | Own (`**Kind:**`) | Not applicable |
| **Executor (`executor`)** | Own (`- executor:`) | Own (`- executor:`) | Own (`**Executor:**`) | Not applicable (assigned per leaf) |
| **Verify-by (`verify-by`)** | Supported (`set-verify-by`) | Supported (`set-verify-by`) | Supported (`**Verify-by:**`) | Not applicable |
| **Waiting-on (`waiting-on`)** | Supported (`set-waiting-on`) | Supported (`set-waiting-on`) | Supported (`**Waiting-on:**`) | Not applicable |
| **Next-up (`next-up`)** | Own (`- next-up: yes\|no`) | Own (`- next-up: yes\|no`) | Driven by initiative `Status: next: NN.T` | Driven by initiative `Status` |
| **Checklist Steps (`## Steps`)** | `step list\|add\|check\|uncheck` (`T036`) | Optional `## Steps` | Inline in `plan.md` task block (`step` CLI currently targets `T###` files only) | Children are `NN.T` tasks (`child add`) |
| **Subtasks / Hierarchy** | Can be expanded to folder (`expand`) & have children (`child add`) | Must `promote` to full task first | Can have `NN.T.M` children (`child add`) | Has `NN.T` children (`child add`) |
| **Attachments (`attach`/`detach`)** | Supported (creates/uses task folder) | Must `promote` first | Not supported on inline `plan.md` nodes | Not supported |
| **Move to Project (`move`)** | Supported (`tasks move T### --to-project`) | Supported (`tasks move T### --to-project`) | Not supported (part of initiative `plan.md`) | Not supported |

### 1.2 Tasks (`EmergentTask` `T###`, `InitiativeTask` `NN.T`, `Microtask`, `Initiative` `NN`)

| Element & State Scope | Owner Action | Engine CLI Command (`ai-orch tasks ...`) | Web UI Coverage (Where) | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Project / Category** | **Create Full Task (`tasks new`)** | `new --title <t> --category <c> --priority <P> --priority-reason <r> --goal <g> [--from-note <N>] [--from-use-case <UC> (17.4)]` | **Only from Inbox (`inboxToTask`)!** No general `New Task` button in Backlog/Queue/Tree (`MicrotaskQuickAdd` only creates `XS` microtasks) | **Missing** (only `createMicrotask` in webview) |
| **Project / `micro/`** | **Create / Promote Microtask** | `micro --title <t> --kind <k> ...` / `promote <id> [--category <c>]` | `MicrotaskQuickAdd` in Backlog/Timeline; `Promote` on `TimelineCard`, `TaskTreeView`, `TaskDetailModal` | Webview only |
| **Any Leaf Task** (`open`) | **Start task** (`-> in progress`) | `transition <id> "in progress" --actor owner` | `TaskDetailModal` footer (*only* for `NN.T`; hidden for `T###` where only `Run…` is shown!) | Webview only; missing in Sidebar TreeView |
| **Any Leaf Task** (`open`, `in progress`, `bounced`, `delivered`) | **Launch Agent Run** (implement / verify) | `ai-orch run start --task <id> ...` | `TaskDetailModal` footer (`Run…`) & `TaskRunsPanel` | Webview only |
| **Any Leaf Task** (`open`, `in progress`, `waiting`, `blocked`, `bounced`, `delivered`) | **Pause task** (`-> paused`) | `transition <id> paused --actor owner` | Kanban card icon, Queue row button, `TaskDetailModal` footer (missing in Tree & Timeline) | Webview only |
| **Any Leaf Task** (`paused`) | **Resume task** (`-> open` or `-> in progress`; *engine has no stored prior state*) | `transition <id> open\|"in progress" --actor owner` | Kanban card (`-> open`), Queue row (`-> open`), `TaskDetailModal` (`Resume (Open)` & `Resume (In Progress)`) | Webview only |
| **Any Leaf Task** (`in progress`) | **Mark Delivered** (`-> delivered`) | `transition <id> delivered [--verify-by <target>] [--verify-check <text>]` | `TaskDetailModal` footer (only if `taskRuns.length === 0`) or `TaskRunsPanel` (`Mark Delivered`); no `verify-by` input | Webview only |
| **Any Leaf Task** (`open`, `in progress`, `waiting`) | **Set / Change / Clear `waiting-on`** | `transition <id> waiting --waiting-on <qual>` / `set-waiting-on <id> <qual\|none>` (`T042`) | **Missing in UI and backend!** (`waiting-on` badge is rendered read-only; cannot set, change, or clear `waiting-on` from UI) | **Missing** |
| **Any Leaf Task** (`waiting`) | **Force Unblock** (`-> open` / `in progress`) | `transition <id> open --force-unblock --reason <text>` | **Missing** in UI and backend | **Missing** |
| **Any Leaf Task** (`open`, `in progress`) | **Mark Blocked** (`-> blocked`) | `transition <id> blocked --reason <text>` | **Missing** in UI | **Missing** |
| **Any Leaf Task** (`delivered`) | **Approve / Mark Verified** (`-> verified`) | `transition <id> verified --verifier owner --owner-approved --reason <text>` | `TaskDetailModal` footer (`Approve (Verified)`, `TaskDetailModal.tsx:2333`, passes `verifier="operator:owner"`) | Webview only |
| **Any Leaf Task** (`delivered`, `verified`) | **Validate & Close (1-shot)** (`delivered -> verified -> done`) | `transition <id> done --verifier owner [--reason <text>]` or `close <id> --verifier owner` (`T035`) | **Planned / In-flight (`T075`)** on `Delivered`/`Verified` column headers, card, and detail | **Planned (`T075`)** in Webview; missing in Sidebar TreeView |
| **Any Leaf Task** (`delivered`, `in progress`) | **Close with Caveat / Self-Verified** (`-> done with a caveat`) | `close <id> --self-verified` or `close <id> --caveat <text>` (`T035`) | **Missing** in UI and backend | **Missing** |
| **Any Leaf Task** (`delivered`) | **Bounce to Executor** (`-> bounced`) | `transition <id> bounced --reason <B1..Bn>` | `TaskDetailModal` footer (`Bounce` -> inline textarea) | Webview only |
| **Any Leaf Task** (`verified`) | **Close Task** (`-> done`) | `transition <id> done --actor owner` or `close <id>` | `TaskDetailModal` footer (`Close Task (Done)`, `TaskDetailModal.tsx:2356`) | Webview only |
| **Bulk (`delivered` / `verified`)** | **Bulk Validate & Close / Close Verified** | `close --verified [--dry-run] [--expect-plan-hash <h>]` (`T035`, `verified` only; no atomic batch CLI for arbitrary task IDs yet) | **Planned (`T075`)** as per-task loop in backend; needs atomic batch CLI command (see §3.5) | **Planned (`T075`)** |
| **Any Leaf Task** (non-terminal) | **Drop Task** (`-> dropped`) | `transition <id> dropped --reason <text>` | **Missing** in UI (cannot drop a task from UI!) | **Missing** |
| **Any Leaf Task** (`done`, `done with a caveat`, `dropped`) | **Reopen to Open** (`-> open`) | `reopen <id> --to open --reason <text> [--expect-plan-hash <h>]` | `TaskTreeView` row button (`Reopen`); **missing** in `TaskDetailModal` and Kanban `Done` column! | Webview (`TaskTreeView` only) |
| **Any Leaf Task** (`done`, `done with a caveat`, `dropped`) | **Reopen to Delivered + Request Verification** (`-> delivered`) | `reopen <id> --to delivered --verify-by <target> [--verify-check <text>] --reason <text>` (`T063`) | **Missing** in UI and backend (backend `/reopen` does not pass `--to` or `--verify-by`) | **Missing** |
| **Any Task** (any state) | **Set Priority** (`P0`–`P3` + `priority-reason`) | `set-priority <id> <P0-P3> [--reason <text>] [--dry-run] [--expect-task-hash <h>]` | `TimelineCard` only (`TimelineCard.tsx:526` -> `TimelineView.tsx:330`: 4 clicks + full diff modal); **read-only** in Kanban, Queue, Tree, and `TaskDetailModal`! | Webview (`TimelineCard` only) |
| **Task with Own Size** | **Set Size** (`XS`–`XL`) | `set-size <id> <XS-XL> [--dry-run] [--expect-task-hash <h>]` | `TimelineCard` only (4 clicks + full `ConfirmDialog` modal); read-only elsewhere | Webview (`TimelineCard` only) |
| **Any Leaf Task** | **Set Executor / Assignee** | `set-executor <id> <executor> [--dry-run] [--expect-task-hash <h>]` | **Missing in UI and backend!** (`server.py` has no `/executor` route; UI displays `executor` as static text everywhere) | **Missing** |
| **Any Leaf Task** | **Request Verification (`verify-by` + `check`)** | `set-verify-by <id> <target> [--check <text>]` / `request-verification` (`T044`) | **Missing in UI and backend!** (`server.py` has no `/verify-by` or `/verification-queue` route) | **Missing** |
| **Any Leaf Task** | **Set Kind** (`feature`, `bug`, `fix`, `chore`, `docs`, `investigation`) | `set-kind <id> <kind> [--dry-run] [--expect-task-hash <h>]` | Backend route & `api.setKind` exist, **but no UI component calls `setKind`!** `KindBadge` is non-clickable everywhere | **Missing** (bridge exists, no UI trigger) |
| **Any Task** | **Edit Labels** (`add`/`remove`/`to`) | `set-labels <id> --to <labels...> [--dry-run] [--expect-task-hash <h>]` | `TaskDetailModal` (`Edit` link -> `LabelEditorModal` -> `ConfirmDialog`: 6 clicks) | Webview (`TaskDetailModal` only) |
| **Any Task** | **Edit Short Title** (`short`) | `set-short <id> <short> [--dry-run] [--expect-task-hash <h>]` | `TaskDetailModal` header (inline input, auto preview+apply in 2 clicks) | Webview (`TaskDetailModal` only) |
| **Any Task** | **Edit Dependencies** (`depends-on`) | `set-deps <id> --add/--remove [--dry-run] [--expect-task-hash <h>]` | `TimelineCard` only (`+ Add` / `×` -> full `ConfirmDialog` modal); read-only in `TaskDetailModal` | Webview (`TimelineCard` only) |
| **Any Task** | **Link / Unlink Use Cases** (`use-cases`) | *Initiative 17 (`17.2`)*: `link <id> UC###` / `unlink <id> UC###` | *Covered by Initiative 17 (`17.9`–`17.10`)* | *Covered by Initiative 17 (`17.10`)* |
| **Emergent Task** (`T###`) | **Toggle `next-up` (`yes`\|`no`)** | Header field `next-up: yes\|no` *(needs `set-next-up` subcommand in engine)* | **Missing!** Queue empty-state tells user to edit Markdown by hand (`**Next up:** yes`) | **Missing** |
| **Emergent Task** (`T###`) | **Checklist Steps (`## Steps`)** | `step list\|add\|check\|uncheck <id> ...` (`T036`) | **Missing in UI and backend!** Steps are rendered as static Markdown checkboxes | **Missing** |
| **Emergent Task** (`T###`) | **Move to another project** | `move <id> --to-project <slug> [--dry-run] [--expect-task-hash <h>]` | **Missing in UI and backend!** Placement warning chip shows warning but offers no 1-click move | **Missing** |
| **Emergent Task** (`T###`) | **Attach / Detach files** | `attach <id> --file <f>` / `detach <id> --name <n>` | `TaskDetailModal` drag-drop & `Attach…` / `×` (uses `window.confirm` on delete) | Webview only |
| **Container / Open Leaf** | **Add Child Subtask / Expand / Collapse** | `child add <parent> --title ...` / `expand <id>` / `collapse <id>` | `TaskTreeView` row buttons & `TaskDetailModal` footer | Webview only |
| **Initiative** (`NN` all leaves done) | **Ship Initiative to `done/NN-slug/`** | `ship <NN> [--dry-run] [--expect-plan-hash <h>]` | **Missing in UI and backend!** | **Missing** |
| **Any Task** | **Copy Handoff / Open File** | `show <id>` (`handoff`, `file_path`) | Queue row (`Handoff`), Tree row (copy icon), `TaskDetailModal` (`Copy Prompt`); missing on Kanban card | Sidebar TreeView inline icons (`copyHandoff`, `openTaskFile`) + Webview |
| **Any Task** | **Contextual AI Chat on Task** (`T074`) | *Spec `T074`*: scoped chat turn with task + linked UC/spec/question/run context | *Covered by `T074` (`tasks/specs/contextual-element-chat.md`)* | *Covered by `T074`* |

### 1.3 Use Cases (`UC###`) — Current Engine vs. Initiative 17

Per `use-cases-drive-tasks.md` (Initiative 17 `17.5` / `17.6`), a Use Case has two orthogonal lifecycle fields:
- **`approval`** (stored header): `proposed` | `approved` | `deprecated`.
- **`stage`** (derived pure function from linked tasks & validation state): `draft` (no linked tasks & not ready), `planned` (all linked tasks `open`/`waiting`), `in development` (at least one linked task active/done, not all `done`), `ready` (all linked tasks `done`, never validated), `ready (revalidation pending)` (a linked task was modified/delivered after `last-tested`), `verified` (all linked tasks `done` and `last-verdict: pass`), `failing` (`last-verdict: fail`), `partial` (`last-verdict: partial`), `untested` (`verification-type: manual` or placeholder command, never tested).

| Element & Stage / Approval | Owner Action | Engine CLI Command (`ai-orch tasks use-cases ...`) | Web UI Coverage & Defects | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Use Case** (new) | **Create Use Case** | `use-cases create [--id UC###] --title ...` | `UseCasesManager` (`New Use Case` modal; hardcodes `status: 'active'`) | Webview (Create only); Sidebar TreeView opens raw `.md` file |
| **Use Case** (existing) | **Edit Use Case Metadata / Body (DEFECT!)** | **No `use-cases edit` command exists!** `create_or_update_use_case` (`tasks_engine.py:7050-7124`) **overwrites the entire file from a template**, wiping `## AI Validation Log`, `last-tested`, and `last-verdict` if `POST /api/use-cases` is called with an existing ID! | **Missing in UI & destructive in Engine/Backend!** Needs non-destructive `use-cases edit <UC>` preserving existing sections and validation history | **Missing** |
| **Use Case** (`approval: proposed\|approved\|deprecated`) | **Set Approval** | *Initiative 17 (`17.5`)*: `use-cases set-approval <UC> approved\|deprecated\|proposed` | *Covered by Initiative 17 (`17.9`–`17.10`)* | *Covered by Initiative 17* |
| **Use Case** (`stage: ready\|verified\|failing` or `--force`) | **Run Automated Validation Probe** | Today: `use-cases validate <UC> [--timeout 60]`. **Note:** `--force` (to run probe when `stage != ready`) does **not** exist yet in `tasks_engine.py`—it is introduced by **Initiative 17 (`17.6`)** | `UseCasesManager` card (`Validate with AI`) & `UseCaseDetailModal` footer (uses `window.alert()` on error) | Webview only (missing in `useCasesView` sidebar context menu) |
| **Use Case** (any) | **Record Owner / Manual Validation Verdict** | `use-cases record-validation <UC> --verdict pass\|fail\|partial --summary ... --actor owner` (exists today in `tasks_engine.py`, append-only in `## AI Validation Log`) | **Missing in UI and backend!** Only automated probe `validate` is wired | **Missing** |
| **Use Case** (any) | **Create Task from Use Case** / **Link & Unlink Task** | *Initiative 17 (`17.2`, `17.4`)*: `tasks new --from-use-case <UC>` / `tasks link <task> <UC>` / `unlink` | *Covered by Initiative 17 (`17.9`–`17.10`)* (today linked task pills in `UseCasesManager`/`UseCaseDetailModal` are non-clickable spans) | *Covered by Initiative 17* |
| **Use Case** (all ready non-draft UCs) | **Run Validation Campaign** | `use-cases campaign [--filter-actor <a>]` (`T069` skips `draft`, `17.6` gates on readiness) | `UseCasesManager` header (`Run Product Validation Campaign`) | Webview only |
| **Use Case** (any) | **Edit Short Title** | `set-short <UC> <short>` | **Missing** in `UseCaseDetailModal` | **Missing** |
| **Use Case** (any) | **Contextual AI Chat on Use Case** (`T074`) | *Spec `T074`*: scoped AI chat with UC + linked tasks + validation log | *Covered by `T074`* | *Covered by `T074`* |

### 1.4 Blocking & Non-Blocking Questions (`Q###`)

| Element & Status | Owner Action | Engine CLI Command (`ai-orch tasks questions ...`) | Web UI Coverage (Where) | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Question** (new, standalone or task-bound) | **Ask a Question** (blocking `<ids>` or non-blocking `--blocks -`) | `questions ask --question "...?" --blocks <ids\|-> [--from-task <id>] ...` | Only inside `TaskDetailModal` (`Ask a question…` form, always blocks that task); **no standalone `+ Ask Question` button in `DecisionsTab`** (cannot create a non-blocking `--blocks -` or multi-task question from UI!) | Webview (`TaskDetailModal` only) |
| **Question** (`open`) | **Answer Question** (pick option `A..Z` or `open` + optional note) | `questions answer <Q###> --choice <c> [--text <t>] --by owner [--apply-ref <r>] [--changes-result]` | `DecisionsTab` -> `Open Decisions` card radio + `Answer` -> `ConfirmDialog` (3 clicks; **missing** in `TaskDetailModal` where open questions are shown read-only!) | Sidebar `decisionsView` click opens `DecisionsTab` in Webview |
| **Question** (`open` with `origin-run`) | **Answer & Resume Origin Run** | `questions answer` + `run continue` (`/answer-and-resume`) | `DecisionsTab` (`Answer and resume run` -> `ConfirmDialog`) | Webview |
| **Question** (`open`, conditional on done task) | **Answer with `--changes-result`** (spawns follow-up task) | `questions answer <Q###> --choice <c> --changes-result` (`T030`) | **Missing in UI!** Checkbox for `--changes-result` is not exposed in `DecisionsTab` | **Missing** |
| **Question** (`open`) | **Withdraw Question** | `questions withdraw <Q###> --reason <text> --by owner` | `DecisionsTab` (`Withdraw Question…` modal) | Webview |
| **Question** (`answered`, `applied: false`) | **Record Decision Applied** | `questions apply <Q###> --by owner [--ref <ref>] [--note <note>]` (`T041`) | `DecisionsTab` -> `Awaiting Application` sub-tab (`Apply Decision` modal); missing `--apply-ref` checkbox during `Answer` | Webview |
| **Question** (`open` or `answered --force`) | **Move to External Tracker** (`status: moved`) | `questions move <Q###> --to <url> [--reason <r>] [--force]` (`T041`, `T052`) | **Missing in UI and backend!** (`server.py` has no `/move` route; `DecisionsTab` filters only `answered \| withdrawn`, hiding `moved` questions!) | **Missing** |
| **Question** (any) | **Contextual AI Chat on Question** (`T074`) | *Spec `T074`*: scoped AI chat with question options + blocked tasks + specs | *Covered by `T074`* | *Covered by `T074`* |

### 1.5 Inbox Notes (`N###`) & "Process Inbox"

| Element & Status | Owner Action | Engine CLI Command (`ai-orch tasks inbox ...`) | Web UI Coverage (Where) | VS Code Extension Coverage |
| --- | --- | --- | --- | --- |
| **Inbox Note** (new / `draft` / `ready`) | **Add / Edit Note & Attachments** | `inbox add ...` / `inbox edit <N###> --expect-hash <h>` / `attach` / `detach` | `InboxPanel` (`New note` / `NoteEditorModal` with autosave + drag-drop attachments) | Webview only (no Inbox TreeView in VS Code sidebar) |
| **Inbox Note** (`draft` / `ready`) | **Toggle `draft` <-> `ready`** | `inbox edit <N###> --status ready\|draft` | Inside `NoteEditorModal` dropdown only; **no 1-click toggle on the list row** | Webview |
| **Inbox Note** (single note, project, or workspace) | **Process Inbox / Triage with AI & Chat** (owner example, `T074` + `T076`) | Single note: `run start --note <N###> --mode triage` + `accept-triage` + Note Contextual Chat (`T074`). Batch (`Process Inbox` on project/workspace): **missing** on `InboxPanel` header! | Only single-note `Triage with Agent…` inside `NoteEditorModal` (3 clicks to start); **no `Process Inbox` button on `InboxPanel` header or row, and no transition into Contextual Chat on a note** | Webview (`NoteEditorModal` only) |
| **Inbox Note** (`draft` / `ready`) | **Convert to Full Task / Microtask** | `new --from-note <N###> ...` / `inboxToMicrotask` | Inside `NoteEditorModal` (`Convert to Task…` / `Microtask`) | Webview |
| **Inbox Note** (`draft` / `ready`) | **Convert to Use Case** (Spec 17 use-case-first) | `use-cases create` + `inbox resolve <N###> --produced UC###` | **Missing!** Inbox only converts to Task or Microtask, not Use Case | **Missing** |
| **Inbox Note** (`draft` / `ready` / `processing`) | **Resolve (Mark Processed) / Discard** | `inbox resolve <N###> --produced <ids>` / `inbox discard <N###> --reason <r>` | Inside `NoteEditorModal` only; **no quick action or bulk discard on `InboxPanel` rows** | Webview |
| **Inbox Note** (`processed` / `discarded`) | **Reopen Note** (`-> to-analyze/ as ready`) | `inbox reopen <N###>` | Inside `NoteEditorModal` only | Webview |

---

## 2. Gaps, Normative Conflicts, and Defects Found

### 2.1 Honest Click-Count Bottlenecks in Current Code
1. **Priority & Size edits in Timeline take 4 clicks (+ typing) and open a 920px diff modal; impossible everywhere else:**
   - In `TimelineCard.tsx:491-595` and `TimelineView.tsx:330-372`, changing priority requires: (1) click `[P2]` badge, (2) click `[P1]` in popover (`TimelineCard.tsx:526`), (3) type optional reason (`TimelineCard.tsx:546`) and click `Preview` (`TimelineCard.tsx:582`), (4) click `Apply` in `ConfirmDialog` (`TimelineView.tsx:339`).
   - In **Kanban** (`BacklogManager.tsx`), **Queue**, **Tree** (`TaskTreeView.tsx`), and **TaskDetailModal**, `priority`, `size`, `executor`, `kind`, and `verify-by` are static non-interactive spans.
2. **Validate & Close today takes 4 clicks across two modal openings:**
   - On a `delivered` card: (1) click card to open `TaskDetailModal`, (2) click `Approve (Verified)` (`TaskDetailModal.tsx:2333`), which closes the modal via `onClose()` (`TaskDetailModal.tsx:715`), (3) click the card again in the `Verified` sub-column, (4) click `Close Task (Done)` (`TaskDetailModal.tsx:2356`).
3. **Editing Labels takes 6 clicks:**
   - (1) Open `TaskDetailModal`, (2) click `Edit` next to Labels, (3) add/remove label in `LabelEditorModal`, (4) click `Preview Changes`, (5) review `ConfirmDialog`, (6) click `Apply`.
4. **Answering a question blocking a task takes 5 clicks and a tab switch:**
   - `TaskDetailModal` renders open blocking questions read-only (`TaskDetailModal.tsx:1510-1570`). The owner must (1) close `TaskDetailModal`, (2) click `Decisions` in the Navbar, (3) select an option radio on the question card, (4) click `Answer`, (5) click `Apply` in `ConfirmDialog`.
5. **Process Inbox has no header or row entry point:**
   - Processing 4 ready inbox notes requires opening each note modal one by one (`InboxPanel.tsx` -> `NoteEditorModal` -> `Triage with Agent…` -> wait -> `Accept`). There is no `Process Inbox` command on the `InboxPanel` header or note row, and no way to discuss an ambiguous note in a note-scoped chat (`T074`).

### 2.2 Normative Conflict: `verifier: owner` vs. `verification-mode` (`task-and-state-model.md` vs. `tasks_engine.py`)
- **What the normative spec says (`tasks/specs/task-and-state-model.md:125-145`):**
  - `task-and-state-model.md` §3.1 defines four `verification-mode` policies: `independent-session`, `cross-agent` (*"verifier tool family must differ from `executor`"*), `panel` (*"requires >= 2 independent verifiers"*), and `owner` (*"requires explicit human/owner sign-off (`verifier: owner`)"*). Under a strict reading of that table, a task whose `verification-mode` is `cross-agent` or `panel` requires an independent agent/panel verification record before `verified -> done`.
- **What `tasks_engine.py` actually implements (`tasks_engine.py:8935-8952`):**
  - `_is_independent_verifier(executor, actor, verifier)` unconditionally returns `True` whenever `verifier` or `actor` is `"owner"` or `"user"` (line 8943: `if cand_norm in ("owner", "user"): return True`), regardless of the task's `verification-mode`! Furthermore, `T035` and `T075` explicitly rely on `transition <id> done --verifier owner` walking `delivered -> verified -> done` in one command.
- **Resolution needed (see Owner Question `Q-A`):** We should align `task-and-state-model.md` with the owner-centric model: the **owner is the ultimate authority** and can always validate & close any task (`--verifier owner`), but when a task declared `verification-mode: cross-agent` or `panel` (or has a pending `verify-by: <other-workspace>`) and has no prior agent verification record, the UI badge and audit log should explicitly label the closure as an **audited owner override** (e.g. `verifier: owner (override: skipped cross-agent)`), rather than silently pretending a cross-agent run happened.

### 2.3 Destructive Use-Case Edit Defect (`tasks_engine.py:7050`)
- `create_or_update_use_case` in `tasks_engine.py:7050-7124` (backed by `POST /api/use-cases`) overwrites the entire `UC###-*.md` file from a fresh template whenever an existing `id: UC###` is passed. If the UI calls `POST /api/use-cases` to edit a use case's title, priority, actor, or scenario without passing `validation_log`, `last_tested`, and `last_verdict`, **the entire `## AI Validation Log` history and last verdict are wiped out**.
- **Fix required:** Add a non-destructive `ai-orch tasks use-cases edit <UC###>` command (with `--expect-hash`) that parses the existing `UC###` file and updates only the requested header fields or body sections while preserving `## AI Validation Log`, `last-tested`, `last-verdict`, and `approval`.

### 2.4 Normative Preview -> Apply Rule (`control-plane-safety.md:147`) vs. Fast Single-Field Edits
- `control-plane-safety.md` §2.1 (line 147) mandates a two-step UI flow (`Preview` -> user inspects diff in `ConfirmDialog` -> `Apply` with `expect_hash`).
- Applying that rule literally to single-field badge edits (`priority`, `size`, `labels`) is what created the 4-to-6 click modal bottleneck in `TimelineView` and `LabelEditorModal`.
- Rather than violating `control-plane-safety.md` silently, **§3.3 proposes an explicit normative amendment to `control-plane-safety.md` §2.1**: for single-item, single-field edits that have an **exact inverse** (`set-priority`, `set-size`, `set-kind`, `set-executor`, `set-labels`, `set-short`, `set-next-up`, `set-verify-by`, `set-waiting-on`, `step check/uncheck`), the UI may pass the **already-loaded `task_bundle_sha256`** directly to the apply endpoint (1 round-trip, still concurrency-checked by `.ai-orch.lock` + `expect_task_hash`) and surface a toast with `[Undo]`. Multi-file, bulk, and structural mutations keep the mandatory two-step `Preview` -> `ConfirmDialog` -> `Apply` flow.

---

## 3. Interaction Model Proposal (Speed, Safety, Undo & Audit)

### 3.1 Five Interaction Surfaces & Card Density Discipline

1. **Column / Section Header (Bulk Actions on Checked Selection):**
   - **Delivered sub-header:** `[✓✓ Validate & Close (N)… ]` (`T075`), `[⊳ Request Verification…]`.
   - **Verified sub-header:** `[✓ Close Verified (N)…]` (`tasks close --verified`).
   - **Open / In Progress header:** `[⏸ Pause (N)…]`.
   - **Paused header:** `[▶ Resume (N)…]`.
   - **Inbox `To Analyze` header:** **`[✨ Process Inbox (N)…]`** (triage ready notes with AI + open note chat when reasoning is needed).
   - **Decisions `Awaiting Application` header:** `[✓ Mark Applied (N)…]`.
2. **Card / Row Surface (Restrained Density: Inline Pills + 1–2 Primary Actions + `[⋯]` Overflow):**
   - **Clickable metadata pills (2 clicks: open popover -> pick value):** `[P1 ▾]`, `[feature ▾]`, `[@kilo ▾]`, `[UC012]`, `[☆]` (1-click star toggle for `next-up`). Container rows (`Initiative NN`) show their derived state as a non-clickable badge.
   - **1–2 Primary Action buttons (1 click):**
     - `open` leaf: `[▶ Start]` + `[💬]`
     - `in progress` leaf: `[✓ Deliver]` + `[💬]`
     - `waiting` leaf: `[💬 Answer Q###]` + `[💬]`
     - `delivered` leaf: **`[✓✓ Validate & Close ▾]`** + `[💬]`
     - `verified` leaf: **`[✓ Close]`** + `[💬]`
     - `paused` leaf: **`[▶ Resume]`** + `[💬]`
     - `done` / `dropped` leaf: **`[↺ Reopen…]`** + `[💬]`
   - **Consistent Overflow Menu `[⋯]` (or Right-Click anywhere on the card/row):** Holds all secondary actions (`Run with Agent…`, `Pause`, `Bounce…`, `Approve (Verified only)`, `Close with Caveat…`, `Request Verification (verify-by)…`, `Set Size ▸`, `Edit Labels…`, `Set Waiting-on…`, `Move to Project ▸`, `Add Subtask…`, `Copy Handoff`, `Open Markdown File`, `Drop Task…`).
3. **Detail View (`TaskDetailModal`, `UseCaseDetailModal`, Question Card, `NoteEditorModal`):**
   - Header exposes all applicable inline-editable pills (`Priority`, `State` for leaves, `Kind`, `Size`, `Executor`, `Verify-by`, `Waiting-on`, `Use Cases`, `Labels`, `Short Title`, `Next-up ★`).
   - Interactive `## Steps` checkboxes (`tasks step check/uncheck`) + `+ Add step…` input on emergent tasks.
   - Inline answer controls on open blocking `Q###` cards inside `TaskDetailModal`.
   - Quick AI Chat bar + expandable Contextual Chat drawer (`T074`).
4. **VS Code Native Sidebar TreeViews (`nextUpView`, `initiativesView`, `decisionsView`, `useCasesView`):**
   - Since VS Code `TreeItem` rows cannot render React popovers, parity is achieved through native VS Code idioms:
     - **Click tree item:** Opens the item's Detail Modal in the AI Orchestration Dashboard Webview (see `Q-G`).
     - **Hover inline icons (`"group": "inline"`, max 3):**
       - On `delivered`/`verified` task: `[$(check-all)] Validate & Close`, `[$(comment-discussion)] Chat on Task`, `[$(go-to-file)] Open File`.
       - On `open`/`in progress` task: `[$(debug-pause)] Pause`, `[$(comment-discussion)] Chat on Task`, `[$(clippy)] Copy Handoff`.
       - On Use Case: `[$(beaker)] Validate Use Case`, `[$(comment-discussion)] Chat on Use Case`, `[$(go-to-file)] Open File`.
     - **Right-click context menu (`view/item/context`):** Full command palette for that item (`Set Priority…` via `vscode.window.showQuickPick`, `Set Executor…`, `Transition State…`, `Validate & Close`, `Request Verification…`, `Reopen…`, `Copy Handoff`, `Open Markdown File`).
5. **Keyboard Shortcuts (1 Key When Focused):**
   - When a card, row, or detail modal has keyboard focus: `v` (`Validate & Close` / `Validate UC`), `p` (open Priority menu, then `1`–`4`), `e` (open Executor menu), `s` (open State menu), `l` (open Labels menu), `u` (open Use Cases menu), `c` or `/` (focus Contextual AI Chat), `Space` (toggle Pause/Resume or step checkbox).

### 3.2 Action-by-Action Reversibility & Undo Contract (No Blanket "Undo")

We distinguish strictly between **Exact Inverse (`[Undo]`)**, **Compensating Action (`[Reopen]` / `[Uncheck]`)**, and **Non-Reversible / Append-Only** mutations:

| Action Category | Concrete Actions | Post-Mutation Toast Action | Mechanics & Hash Handling |
| --- | --- | --- | --- |
| **1. Exact Inverse** (Single-field metadata & checklist edits) | `set-priority`, `set-size`, `set-kind`, `set-executor`, `set-short`, `set-labels`, `set-next-up`, `set-verify-by`, `set-waiting-on`, `step check` / `uncheck`, `tasks link` / `unlink`, `use-cases set-approval`, `inbox edit --status draft\|ready` | **`[Undo]`** (shown for 6 seconds) | The apply response returns the **new `task_hash`** (`after_hash`) and the UI remembers `{ previous_value, after_hash }`. Clicking `[Undo]` calls the exact same command with `previous_value` and `expect_task_hash = after_hash`. If the file was modified again in the meantime, `expect_task_hash` fails with `409 Conflict` and the conflict banner is shown. |
| **2. Compensating Action** (Terminal task/note closures) | `Validate & Close` (`delivered -> verified -> done`), `Close` (`verified -> done`), `Close with Caveat`, `Drop Task` (`-> dropped`), `inbox resolve`, `inbox discard` | **`[Reopen]`** (never labelled `Undo`) | Closing a task moves the file to `tasks/done/` (`git mv`), sets `verifier`, and appends 1–2 audit lines to `## Log`. It cannot be "un-happened" silently. Clicking **`[Reopen]`** in the toast runs `tasks reopen <id> --to <delivered\|open> --reason "Reopened immediately from UI"` (or `inbox reopen <N###>`), which restores the file and appends an honest reopen log line. |
| **3. Forward Non-Terminal Transitions (No Inverse Button)** | `Start` (`open -> in progress`), `Deliver` (`in progress -> delivered`), `Approve` (`delivered -> verified`), `Bounce` (`delivered -> bounced`), `Pause` (`-> paused`), `Resume` (`paused -> open\|in progress`) | **Status toast only** (no `[Undo]` button) | The engine does not store prior state on `paused`, and `in progress -> open` or `verified -> delivered` are not legal backward transitions in `task-and-state-model.md`. The user can use the state pill or card button (`Pause` / `Resume` / `Bounce`) to move to the next legal state. |
| **4. Append-Only / Multi-Entity Mutations (No Inverse)** | `questions answer`, `questions apply`, `questions withdraw`, `questions move`, `use-cases record-validation`, `use-cases validate`, `tasks new`, `tasks promote`, `tasks expand`/`collapse`, `tasks ship` | **Status toast only** (or Level 1/2/3 confirmation beforehand) | Answering a question unblocks dependent tasks and logs an event; validation probes append to `## AI Validation Log`. These have no automatic inverse. |

### 3.3 Explicit Amendment to `control-plane-safety.md` §2.1 & 409 Conflict Handling

1. **Proposed Amendment to `control-plane-safety.md` §2.1 (Fast-Path Concurrency Token for Exact-Inverse Field Edits):**
   - *Current rule (`control-plane-safety.md:147`):* Every write must call `--dry-run` first, display a preview diff, and then call `--apply --expect-*-hash`.
   - *Proposed amendment:* For **Category 1 (Exact Inverse) single-field edits** (`set-priority`, `set-size`, `set-kind`, `set-executor`, `set-labels`, `set-short`, `set-next-up`, `set-verify-by`, `set-waiting-on`, `step check/uncheck`, `link`/`unlink`, `set-approval`), the UI may pass the **`task_bundle_sha256` already loaded with the card/detail payload** directly as `expect_task_hash` to the mutation endpoint in a **single round-trip**, without a prior `--dry-run` modal. The engine still acquires `.ai-orch.lock` and verifies `expect_task_hash == current_hash` before writing.
   - All **Category 2, 3, and 4 mutations**—and all **bulk, structural, or multi-file mutations**—continue to require an explicit preview hash or confirmation step (see Owner Question `Q-E`).
2. **Strict 409 Conflict Handling (NEVER Auto-Retry Silently):**
   - If any mutation returns **`409 Conflict` (`hash_mismatch`)**, it means another actor (an executor run, an orchestrator session, or a git pull) modified the task since the UI rendered it.
   - **The UI must NEVER silently refetch the new hash and re-apply the mutation** (which would blindly overwrite concurrent changes, e.g. changing priority or closing a task whose spec or state just changed).
   - Instead, on `409 Conflict`, the UI **refetches the updated element**, highlights what changed in an inline conflict banner/popover (`"T075 was updated by another session while you were viewing it — review the updated state and click Apply again"`), and lets the owner confirm or cancel with one click.

### 3.4 Audit Trail & Provenance for Token-Authenticated UI Calls

- **What the backend actually knows:** A request arriving at `ai-orchestration-ui/backend/server.py` with `X-AI-Orch-Token` (or via the VS Code extension `CliClient`) proves that the caller holds the local UI/extension capability token on the user's machine. **It does NOT cryptographically prove a physical human mouse click** (a local process or browser automation with access to the token could call the endpoint).
- **Honest Audit Wording & Provenance Metadata:**
  - Every UI-initiated CLI command passes `--actor owner` (or `--verifier owner` when verifying/closing) **plus a provenance tag** in the audit log / event payload: `via: web-ui` or `via: vscode-ext`, alongside the short `request_id` (and `client_session_id` of the browser tab / webview instance).
  - Log lines written to `## Log` / `PROGRESS.md` use accurate, non-overclaiming wording:
    - Standard closure (when `verification-mode: owner` or already verified):
      `- 2026-10-27, owner (via web-ui): state delivered -> verified (verifier: owner) — Validated & closed from UI[: <note>]`
    - Owner override closure (when `verification-mode` was `cross-agent` / `panel` or `verify-by` was another workspace, and no independent agent verification was recorded yet):
      `- 2026-10-27, owner (via web-ui): state delivered -> verified (verifier: owner [owner-override: verification-mode=cross-agent]) — Validated & closed from UI[: <note>]`

### 3.5 Bulk Actions: Frozen Selection Scope & Atomic Batch Execution

When the owner clicks a column-header bulk action (e.g. `[✓✓ Validate & Close (3)…]` on the `Delivered` sub-column):
1. **Bulk Scope (Frozen at Preview + Per-Row Checkboxes):**
   - Clicking the column header button snapshots the **exact list of task IDs currently visible in that column under the active filters** (search query, label filter, project filter, `Next-up only`).
   - The Level 2 confirmation dialog displays those `N` tasks with **individual checkboxes** (all checked by default, so the owner can uncheck 1 task they want to keep open) and shows a filter summary banner if a filter is active (`"Showing 3 of 7 delivered tasks (filtered by label #ui)"`).
   - Even if a WebSocket event arrives while the dialog is open, the batch operates **only on the explicitly checked IDs and their previewed hashes**—never on a live wildcard query.
2. **Atomic Engine Batch Command (`all-or-none` under one `.ai-orch.lock`):**
   - Today, `tasks close --verified` (`T035`) only supports tasks already in `verified`, and `T075`'s initial step 1 loops `transition <id> done` one task at a time in the backend. Looping in the backend means if task 3 of 5 fails a guard (e.g. a placeholder step or a concurrent edit), tasks 1–2 are already committed and moved to `tasks/done/`, leaving a partial state.
   - **Proposed Engine Command (`tasks batch-transition` / `close --ids`):** Add `ai-orch tasks close <id1> [<id2> ...] --verifier owner [--reason <note>] [--dry-run] [--expect-plan-hash <hash>]` to `tasks_engine.py`:
     - In `--dry-run`, it validates all guards and computes the transitions for every listed ID under `.ai-orch.lock`, returning a single deterministic `plan_hash` (and per-task validation warnings/errors if any task is ineligible).
     - On apply (`--expect-plan-hash <hash>`), it acquires `.ai-orch.lock` once, verifies that **every** listed task's hash still matches the preview, and applies all file updates, `git mv` operations, and `00-INDEX.md` sync **atomically (all-or-none)**.
   - *Relation to `T075`:* `T075` can land its narrow UI/backend slice immediately, and Task `18.1` upgrades the backend endpoint to call the atomic engine batch command instead of a Python loop.

---

## 4. Complete Action Matrix: Clicks Today vs. Proposed

### 4.1 Task Action Matrix by State & Surface

*(Note on click counts: **1 click** = direct button on card/row; **2 clicks** = click inline pill -> click value in popover; **1 key** = keyboard shortcut when card/row/modal is focused.)*

| State / Scope | Action Name (English UI Label) | Surface Placement | Confirmation & Post-Action Toast | Engine Command | Clicks Today (Web UI) | Clicks Proposed |
| --- | --- | --- | --- | --- | --- | --- |
| **Project / Board** | **New Full Task…** | Board/Queue/Tree header `[+ New Task…]` | Modal form (`title`, `category`, `priority`, `reason`, `goal`) | `tasks new --title ...` | **Impossible** (only from Inbox note or Microtask) | **2 clicks** (`+ New Task` -> `Create`) |
| **Leaf & Container** (where applicable per §1.1) | **Change Priority** (`P0`–`P3`) | Clickable `[P1 ▾]` pill on Card, Queue, Tree, Timeline, Detail + Key `p` (`1`–`4`); VS Code TreeView context menu | **Immediate** (1 round-trip with loaded `expect_task_hash`; inline reason input if `priority-reason` is empty) + Toast **`[Undo]`** | `set-priority <id> <P> [--reason <r>] --expect-task-hash <h>` | **4 clicks + typing** in Timeline (`TimelineCard.tsx:526`, `TimelineView.tsx:330`); **Impossible** elsewhere | **2 clicks** (pill -> value) or **2 keys** (`p` -> `2`) |
| **Leaf Task** | **Change Executor** | Clickable `[@kilo ▾]` pill on Card, Queue, Tree, Detail + Key `e`; VS Code TreeView context menu | **Immediate** (`expect_task_hash`) + Toast **`[Undo]`** | `set-executor <id> <exec> --expect-task-hash <h>` | **Impossible** (CLI only) | **2 clicks** (pill -> executor) |
| **Task with Own Size** | **Change Size** (`XS`–`XL`) | Clickable `[M ▾]` pill on Queue, Tree, Timeline, Detail, Card `[⋯]` | **Immediate** (`expect_task_hash`) + Toast **`[Undo]`** | `set-size <id> <size> --expect-task-hash <h>` | **4 clicks** in Timeline (with diff modal, `TimelineView.tsx:353`); **Impossible** elsewhere | **2 clicks** (pill -> size) |
| **Leaf Task** | **Change Kind** (`feature`, `fix`, ...) | Clickable `[feature ▾]` badge on Card, Queue, Tree, Timeline, Detail | **Immediate** (`expect_task_hash`) + Toast **`[Undo]`** | `set-kind <id> <kind> --expect-task-hash <h>` | **Impossible** (no UI trigger) | **2 clicks** (badge -> kind) |
| **Any Task** | **Edit Labels** | Clickable `[+ tag]` chip on Detail, Tree, Queue, Card `[⋯]` + Key `l` | **Immediate** toggle in popover (`expect_task_hash`) + Toast **`[Undo]`** | `set-labels <id> --add/--remove <lbl> --expect-task-hash <h>` | **6 clicks** (`TaskDetailModal` -> `LabelEditorModal` -> `ConfirmDialog`) | **2 clicks** (chip -> toggle tag) |
| **Emergent Task (`T###`)** | **Toggle Next Up (`★`)** | Star icon `[☆]` / `[★]` on Card, Queue, Tree, Detail | **Immediate** (`expect_task_hash`) + Toast **`[Undo]`** | `set-next-up <id> yes\|no --expect-task-hash <h>` | **Impossible** (manual Markdown edit) | **1 click** |
| **Emergent Task (`T###`)** | **Check / Uncheck / Add Step** (`## Steps`) | Interactive checkboxes & `+ Add step…` in `TaskDetailModal` | **Immediate** (`expect_task_hash`) + Toast **`[Undo]`** | `step check\|uncheck\|add <id> ... --expect-task-hash <h>` | **Impossible** (CLI only) | **1 click** per checkbox |
| **Any Task** | **Link / Unlink Use Cases** (`UC###`) | *Initiative 17 (`17.10`)*: `[UC###]` pill / `[+ UC]` popover + Key `u` | **Immediate** toggle + Toast **`[Undo]`** | `link <id> <UC>` / `unlink <id> <UC>` (`17.2`) | **Impossible** (in flight in `17.10`) | **2 clicks** (popover -> toggle UC) |
| **Any Task** | **Chat on Task (`💬`)** (`T074`) | `[💬]` button on Card, Queue, Tree, Detail + Key `c` / `/` | Opens Contextual Chat drawer / focuses quick bar | *Spec `T074`*: element-scoped chat turn | **Impossible** (global chat only) | **1 click** (or key `c`) |
| **1. `open` Leaf** | **Start Task** (`-> in progress`) | Card primary button `[▶ Start]`, State pill, Detail footer | **Immediate** (`expect_task_hash`); status toast (no inverse) | `transition <id> "in progress" --actor owner` | **2 clicks** for `NN.T` (Detail -> Start); **Impossible** for `T###` without Run | **1 click** on card |
| **1. `open` Leaf** | **Run with Agent…** | Card `[⋯]` / Detail footer `[⚡ Run…]` | `RunDialog` preview -> Start | `run start --task <id> ...` | **3–4 clicks** (Detail -> Run… -> Start) | **2–3 clicks** |
| **1. `open` / `in progress` Leaf** | **Pause Task** (`-> paused`) | Card icon `[⏸]`, Queue row `[Pause]`, Detail footer, Column header `[⏸ Pause (N)…]` | Single: **Immediate** (`expect_task_hash`); Bulk: **Level 2 dialog** | `transition <id> paused --actor owner` | **1 click** on Kanban/Queue (missing `expect_task_hash`); **2 clicks** in Detail | **1 click** (with `expect_task_hash`) |
| **2. `in progress` Leaf** | **Mark Delivered** (`-> delivered`) | Card primary button `[✓ Deliver ▾]`, State pill, Detail footer | **Immediate** (or split `[▾]` to set `verify-by` at delivery) | `transition <id> delivered --actor owner [--verify-by <t>]` | **2 clicks** (Detail -> Mark Delivered, hidden if runs exist) | **1 click** on card |
| **3. `waiting` / `blocked` Leaf** | **Answer Blocking Question** (`Q###`) | Card button `[💬 Answer Q011]` -> inline popover, or inline inside `TaskDetailModal` | **Immediate** on option click + `Answer` (no inverse) | `questions answer <Q###> --choice <c> --by owner` | **5 clicks** (close Detail -> Decisions tab -> select -> Answer -> ConfirmDialog) | **2 clicks** inline from card or Task Detail |
| **3. `waiting` Leaf** | **Set / Change / Clear `waiting-on`** | Clickable `[Waiting on: … ▾]` pill in Detail & Card `[⋯]` | **Immediate** (`expect_task_hash`) + Toast **`[Undo]`** | `set-waiting-on <id> <qual\|none> --expect-task-hash <h>` | **Impossible** (CLI only) | **2 clicks** |
| **3. `waiting` Leaf** | **Force Unblock** (`-> open`) | Detail footer / Card `[⋯]` -> `Force Unblock…` | **Inline reason popover** (1 input + `Enter`) | `transition <id> open --force-unblock --reason <r>` | **Impossible** in UI | **2 clicks** + reason |
| **5. `delivered` Leaf** | **Validate & Close** (`delivered -> verified -> done`) (`T075`) | **Primary button `[✓✓ Validate & Close ▾]`** on Card, Detail footer, Tree row, VS Code TreeView inline icon + Key `v` | **1-click immediate** on single card (or split `[▾]` for note / override prompt if `cross-agent`); Toast offers **`[+ Add Note]` & `[Reopen]`** | `transition <id> done --actor owner --verifier owner --owner-approved [--reason <note>]` | **4 clicks across 2 modal openings** (`TaskDetailModal.tsx:2333`, `715`, `2356`) | **1 click** on card (or key `v` when focused) |
| **5. `delivered` (Bulk)** | **Validate & Close Checked (`N`)** (`T075`) | **Delivered Sub-Column Header** `[✓✓ Validate & Close (N)…]` | **Level 2 Checklist Dialog** (frozen visible IDs + checkboxes + optional shared note, `expect_plan_hash`) | Atomic batch `close <ids...> --verifier owner --owner-approved --expect-plan-hash <h>` | **Impossible** (`4 × N` clicks) | **2 clicks** (Header button -> Confirm) |
| **5. `delivered` Leaf** | **Approve Only (Mark Verified)** (`-> verified`) | Card split-button `[▾]` -> `Mark Verified Only`, State pill, Detail footer | **Immediate** (`expect_task_hash`); status toast | `transition <id> verified --actor owner --verifier owner --owner-approved` | **2 clicks** (Open Detail -> Approve, closes modal) | **2 clicks** from card split menu or **1 click** in Detail |
| **5. `delivered` Leaf** | **Bounce** (`-> bounced`) | Card `[⋯]` / Detail footer `[↩ Bounce…]` | **Inline reason popover** (`B1..Bn` findings) | `transition <id> bounced --actor owner --reason <r>` | **3 clicks** (Open Detail -> Bounce -> Confirm Bounce) | **2 clicks** + reason |
| **5. `delivered` Leaf** | **Request Verification (`verify-by`)** | Clickable `[Verify-by: + ▾]` pill on Delivered card & Detail | **Immediate** on target selection (`expect_task_hash`) + Toast **`[Undo]`** | `set-verify-by <id> <target> [--check <c>] --expect-task-hash <h>` | **Impossible** (CLI only) | **2 clicks** |
| **6. `verified` Leaf** | **Close Task** (`-> done`) | **Primary button `[✓ Close]`** on Card, Detail footer, Tree row + Key `v` | **1-click immediate** (`expect_task_hash`) + Toast **`[Reopen]`** | `transition <id> done --actor owner` | **2 clicks** (Open Detail -> Close Task) | **1 click** on card |
| **6. `verified` (Bulk)** | **Close All Verified (`N`)** | **Verified Sub-Column Header** `[✓ Close Verified (N)…]` | **Level 2 Checklist Dialog** (`expect_plan_hash`) | `close --verified --expect-plan-hash <h>` | **Impossible** (`2 × N` clicks) | **2 clicks** |
| **7. `paused` Leaf** | **Resume Task** (`-> open` or `-> in progress`) | Card primary button `[▶ Resume ▾]` (`open` default, `[▾]` for `in progress`), Column header `[▶ Resume (N)…]` | Single: **Immediate** (`expect_task_hash`); Bulk: **Level 2 dialog** | `transition <id> open\|"in progress" --actor owner` | **1 click** on card (`-> open` only); **Impossible** in bulk | **1 click** (`-> open`) or **2 clicks** (`-> in progress` / Bulk) |
| **8. `done` / `done with a caveat` / `dropped` Leaf** | **Reopen Task** (`-> open` or `-> delivered`) | Card primary button `[↺ Reopen…]`, Tree row, Detail footer, Toast `[Reopen]` | **Inline popover** (target `open` vs `delivered`, optional `verify-by`, mandatory `reason`) | `reopen <id> --to open\|delivered [--verify-by <t>] --reason <r>` | **4 clicks** in Tree only (`open` target only); **Impossible** in Kanban/Detail or to `delivered` | **2 clicks** + reason |
| **Any Non-Terminal Leaf** | **Drop Task** (`-> dropped`) | Card `[⋯]` menu -> `Drop Task…`, Detail footer | **Level 1/2 confirmation** requiring drop `reason` + Toast **`[Reopen]`** | `transition <id> dropped --actor owner --reason <r>` | **Impossible** in UI | **2 clicks** + reason |
| **Initiative Container (`NN` all leaves `done`)** | **Ship Initiative** (`-> done/NN-slug/`) | Tree row / Detail header `[📦 Ship Initiative…]` | **Level 3 `ConfirmDialog`** (`--dry-run` -> `--expect-plan-hash`) | `ship <NN> --expect-plan-hash <h>` | **Impossible** (CLI only) | **2 clicks** |

### 4.2 Element View Action Matrix (Use Cases, Questions, Inbox Notes)

| Element View | Action Name (English UI Label) | Surface Placement | Confirmation & Post-Action Toast | Engine Command | Clicks Today | Clicks Proposed |
| --- | --- | --- | --- | --- | --- | --- |
| **Use Cases** (`UseCasesManager` & `UseCaseDetailModal`) | **Set Approval** (`proposed` / `approved` / `deprecated`) | *Initiative 17 (`17.10`)*: Clickable `[PROPOSED ▾]` badge on UC card & Detail header | **Immediate** + Toast **`[Undo]`** | `use-cases set-approval <UC> <val>` (`17.5`) | **Impossible** (in flight in `17.5`/`17.10`) | **2 clicks** |
| **Use Cases** | **Validate with AI** (run probe; `--force` when `stage != ready` per `17.6`) | Card button `[▶ Validate]`, Detail footer, VS Code TreeView inline icon | **Immediate** run (if `stage != ready`, popover offers `[Force Validate]` once `17.6` lands; no `window.alert()`) | `use-cases validate <UC> [--force (17.6)]` | **1 click** (uses `window.alert()` on error) | **1 click** |
| **Use Cases** | **Record Owner Verdict** (`Pass` / `Fail` / `Partial`) | Card `[⋯]` menu & Detail footer `[✓ Record Verdict…]` | **Inline popover** (`Pass` \| `Fail` \| `Partial` + 1-line summary; append-only, no undo) | `use-cases record-validation <UC> --verdict <v> --summary <s> --actor owner` | **Impossible** (CLI only) | **2 clicks** + summary |
| **Use Cases** | **Edit Use Case** (non-destructive!) | Detail `[✎ Edit]` mode + inline `Priority` / `Actor` / `Short` pills | **Immediate** for pills + Toast **`[Undo]`**; Save button for body sections (`expect_hash`) | **New:** `use-cases edit <UC> ... --expect-hash <h>` (preserves `## AI Validation Log`!) | **Impossible** in UI (and `create --id` wipes log!) | **2 clicks** |
| **Use Cases** | **Create Task from UC / Link Task / Navigate to Task** | *Initiative 17 (`17.9`–`17.10`)*: clickable `Task T###` pills + `[+ Task from UC]` + `[+ Link Task ▾]` | Click pill = **1 click** to open task; Link/Unlink = **2 clicks** + Toast **`[Undo]`** | `tasks new --from-use-case <UC>` (`17.4`) / `link` / `unlink` (`17.2`) | **Impossible** (pills are non-clickable spans today) | **1 click** (open) / **2 clicks** (link/create) |
| **Use Cases** | **Chat on Use Case (`💬`)** (`T074`) | Card `[💬]` & Detail quick chat bar / drawer | Opens Contextual Chat | *Spec `T074`*: scoped chat turn on `UC###` | **Impossible** | **1 click** |
| **Questions** (`DecisionsTab` & `TaskDetailModal`) | **Ask Standalone / Non-Blocking Question** | `DecisionsTab` header `[+ Ask Question…]` (`Blocks: none (--blocks -)` or task picker) | Modal form -> Create | `questions ask --question "...?" --blocks <ids\|->` | **Impossible** from `DecisionsTab` (only inside `TaskDetailModal`) | **2 clicks** |
| **Questions** | **Answer Question** (in `DecisionsTab` OR inline in `TaskDetailModal`) | Option radio + `[✓ Answer]` (with `[x] Also mark applied` & `[ ] Changes finished task result` checkboxes) | **2 clicks** (select option -> click `Answer`; Level 2 dialog only if resuming a run or `--changes-result`; no inverse) | `questions answer <Q###> --choice <c> --by owner [--apply-ref <r>] [--changes-result]` | **3 clicks** in `DecisionsTab` (always opens `ConfirmDialog`); **5 clicks** from `TaskDetailModal` | **2 clicks** in both `DecisionsTab` and `TaskDetailModal` |
| **Questions** | **Mark Decision Applied** | `Awaiting Application` card `[✓ Mark Applied]` | **1 click** (uses blocked task ID as default `--ref`, or `[▾]` for custom note; no inverse) | `questions apply <Q###> --by owner --ref <ref>` | **3 clicks** (opens modal every time) | **1 click** |
| **Questions** | **Move to External Tracker** (`status: moved`) | Question card `[⋯]` -> `Move to Tracker…` (+ add `Moved` filter pill in `DecisionsTab`) | **Inline popover** for tracker URL + optional reason | `questions move <Q###> --to <url> [--reason <r>]` | **Impossible** (CLI only; `moved` hidden in UI) | **2 clicks** + URL |
| **Questions** | **Chat on Question (`💬`)** (`T074`) | `[💬 Discuss with AI]` on Question card | Opens Contextual Chat | *Spec `T074`*: scoped chat turn on `Q###` | **Impossible** | **1 click** |
| **Inbox Notes** (`InboxPanel` & `NoteEditorModal`) | **Process Inbox** (Single note, Project, or Workspace — Owner example) | `InboxPanel` header **`[✨ Process Inbox (N)]`** + Row button **`[✨ Process]`** + `NoteEditorModal` | Opens note-focused Contextual Chat / Triage runner with AI triage proposal as the suggested first action (see `Q-F`) | Triage run / Contextual Chat (`T074`) + `accept-triage` | **3–4 clicks per note** inside `NoteEditorModal` only; no header command or chat | **1 click** from header or row |
| **Inbox Notes** | **Toggle `draft` <-> `ready`** | Clickable `[DRAFT ▾]` / `[READY ▾]` pill on `InboxPanel` row | **Immediate** (`expect_hash`) + Toast **`[Undo]`** | `inbox edit <N###> --status ready\|draft --expect-hash <h>` | **3 clicks** (open modal -> dropdown -> close) | **1–2 clicks** on row |
| **Inbox Notes** | **Quick Convert to Task / Microtask / Use Case** | Row `[⋯]` / hover `[⚡ Micro]` `[+ Task]` `[+ UC]` + inside `NoteEditorModal` | `[⚡ Micro]` = **1 click**; `[+ Task]` / `[+ UC]` = **2 clicks** via pre-filled modal | `inboxToMicrotask` / `inboxToTask` / `use-cases create` + `inbox resolve` | **3–4 clicks** (must open `NoteEditorModal` first) | **1–2 clicks** from row |
| **Inbox Notes** | **Resolve / Discard Note** | Row `[⋯]` -> `Resolve…` / `Discard…` + Bulk header action | **Inline reason popover** (single) / **Level 2 dialog** (bulk) + Toast **`[Reopen]`** | `inbox resolve` / `inbox discard` | **3–4 clicks** inside modal only | **2 clicks** from row |

---

## 5. ASCII Mockups

### 5.1 Kanban Column Headers & Restrained Card Density (2-Click Pill Popover + 1-Click Primary Action + `[⋯]` Overflow)

```text
+----------------------------------------------------------------------------------------------------------------------+
| WORKFLOW BOARD                              [+ New Task…] [⚡ Quick Microtask] [☆ Next-up] [⏸ Paused (2)] [👁 Done] |
+======================================================+===============================================================+
| ● IN PROGRESS (3)                    [⏸ Pause (3)…]  | ● DELIVERED / VERIFIED (4)                                    |
+------------------------------------------------------+---------------------------------------------------------------+
| +--------------------------------------------------+ | Delivered — needs verification (3) [✓✓ Validate & Close (3)…] |
| | [P1 ▾] [⚙ engine ▾]                   [☆] [⋯]    | |                                    [⊳ Request Verification… ] |
| | T070 · Reassign su sessione attuale              | | +-----------------------------------------------------------+ |
| | orchestrator reassign binds interactive session  | | | [P1 ▾] [📐 method ▾]   Verify-by: [owner ▾]    [★] [⋯]    | |
| | [@kilo ▾] [UC028]            [💬] [✓ Deliver ▾]  | | | T073 · Studio pannello orchestratori                      | |
| +--------------------------------------------------+ | | Study: cross-workspace orchestrator control plane         | |
|          |                                           | | [@kilo ▾] [UC028]        [💬] [✓✓ Validate & Close ▾]     | |
|          v  (Click 1: open [P1 ▾] pill;              | +-----------------------------------------------------------+ |
|              Click 2: pick P0-P3 -> immediate apply) |                                      |                        |
|   +--------------------------------------+           |   (Click [✓✓ Validate & Close] -> 1-click immediate closure!  |
|   | Set Priority for T070          [Esc] |           |    Click [▾] or [⋯] for secondary options:)                   |
|   | [P0]  [*P1*]  [P2]  [P3]             |           |   +-------------------------------------------------------+   |
|   | Reason: [Requested by owner N068___] |           |   | ✓✓ Validate & Close now (verifier: owner)        [v] |   |
|   +--------------------------------------+           |   | ✓✓ Validate & Close with note…                       |   |
|                                                      |   | ✓  Approve only (move to Verified, keep open)        |   |
|                                                      |   | ⚠  Close with caveat (self-verified / note)…         |   |
|                                                      |   | ↩  Bounce to executor…                               |   |
|                                                      |   +-------------------------------------------------------+   |
|                                                      | - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - |
|                                                      | Verified — ready to close (1)        [✓ Close Verified (1)…]  |
|                                                      | +-----------------------------------------------------------+ |
|                                                      | | [P2 ▾] [🔧 fix ▾]      Verifier: owner         [☆] [⋯]    | |
|                                                      | | T069 · Campagna senza bozze                               | |
|                                                      | | [@kilo ▾]                          [💬] [✓ Close]         | |
|                                                      | +-----------------------------------------------------------+ |
+======================================================+===============================================================+
| Toast after 1-click Priority edit (Exact Inverse -> shows [Undo]):                                                   |
| +------------------------------------------------------------------------------------------------------------------+ |
| | ✓ T070 priority changed P2 -> P1.                                                                   [Undo (6s)]  | |
| +------------------------------------------------------------------------------------------------------------------+ |
| Toast after 1-click Validate & Close (Compensating Action -> shows [Reopen], never fake Undo):                       |
| +------------------------------------------------------------------------------------------------------------------+ |
| | ✓ T073 validated & closed (verifier: owner).                                        [+ Add Note]  [Reopen (6s)]  | |
| +------------------------------------------------------------------------------------------------------------------+ |
+----------------------------------------------------------------------------------------------------------------------+
```

### 5.2 Bulk "Validate & Close" Confirmation Dialog (`T075` — Frozen Visible Selection & Atomic Plan Hash)

```text
+==============================================================================+
| ✓✓ Validate & Close Delivered Tasks (3 of 3 visible selected)            [×] |
+------------------------------------------------------------------------------+
| Active filter: Project = ai-orchestration · Showing 3 delivered tasks.       |
| All checked tasks will be atomically verified (`verifier: owner`) and        |
| closed (`done`) under plan hash `9f3a1c2e…`:                                 |
|                                                                              |
|  [x] T073 (Studio pannello orchestratori) [mode: owner]                      |
|  [x] T075 (Valida e chiudi da UI)         [mode: owner]                      |
|  [x] 16.9b (Web UI multi-project)         [mode: cross-agent ⚠ override]     |
|                                                                              |
|  ⚠ Note: 16.9b declares `verification-mode: cross-agent` with no prior       |
|    cross-agent run. Closing as owner records an audited `owner-override`.    |
|                                                                              |
| Validation Note (optional, recorded in each task's ## Log / PROGRESS.md):    |
| +--------------------------------------------------------------------------+ |
| | Validated live in the UI by owner.                                       | |
| +--------------------------------------------------------------------------+ |
|                                                                              |
| [Cancel]                                    [✓✓ Validate & Close 3 Tasks]    |
+==============================================================================+
```

### 5.3 Task Detail Modal: Inline Pills, Interactive Steps, Inline Questions & Contextual AI Chat (`T074`)

```text
+======================================================================================================================+
| Initiatives / 17 / 17.5                                                                                          [×] |
| [P1 ▾] [ai-orch] 17.5 (Stadio degli use case ✎) [✨ feature ▾] [M ▾] [State: waiting ▾] [★ Next-up]                  |
| Ciclo di vita: approvazione e stadio derivato                                                                        |
+----------------------------------------------------------------------------------------------------------------------+
| Executor: [@kilo ▾]  | Waiting-on: [Q011 ▾]        | Verify-by: [owner ▾]        | Use Cases: [UC012 ×] [+ Link UC▾] |
| Mode: [owner ▾]      | Depends on: [17.1 ×] [+ ▾]  | Labels: [#ui ×] [#uc ×] [+] | File: tasks/17-.../plan.md [Open] |
+======================================================================================================================+
| [📄 Specification & Steps]  [⚡ Runs (1)]  [📎 Attachments (0)]         [Structured | Raw]   [💬 Contextual Chat (2)] |
+----------------------------------------------------------------------+-----------------------------------------------+
| ## Goal                                                              | 💬 CHAT ON 17.5 (Stadio degli use case)       |
| Spec §3 according to Q011: `approval` field with migration from      | Context: 17.5 + spec/use-cases-drive-tasks.md |
| `status`, `stage` as pure function; shown by show/list/index.        | + Q011 + UC012 · Session: claude (sonnet) [▾] |
|                                                                      | --------------------------------------------- |
| ## Steps  (Click checkbox to toggle in place via `tasks step check`) | [Owner 15:02]: Can we also include `partial`  |
| - [x] 1. Parse `approval:` header and fallback from legacy `status:` | in the migration from status to last-verdict? |
| - [ ] 2. Implement pure `compute_use_case_stage(uc, linked_tasks)`   |                                               |
| - [ ] 3. Expose `approval` and `stage` in `use-cases list/show`      | [Claude 15:02]: Done — updated step 1 of      |
| [+ Add step…_______________________________________________] [Add]   | `17.5` and §3 of `use-cases-drive-tasks.md`   |
|                                                                      | so `partial` maps to `approval: approved` and |
| ## Blocking Questions (1 Open — Answer directly here in 2 clicks!)   | `last-verdict: partial`.                      |
| +------------------------------------------------------------------+ |   ✓ task.updated: 17.5 (hash 4c92..)          |
| | Q011 (Approvazione vs stadio UC) · Open · Blocks: 17.5           | |                                               |
| | Separiamo l'approvazione di uno use case dal suo stadio derivato?| | [Ask or tell AI about 17.5…                 ] |
| | (o) A — Sì: campo `approval` + `stage` derivato [★ Recommended]  | | [____________________________________] [Send] |
| | ( ) B — No: un solo campo con `draft (approved)`                 | +-----------------------------------------------+
| | Note: [________________________________________________________] |
| | [x] Mark applied (`--apply-ref 17.5`)     [✓ Answer & Unblock]   |
| +------------------------------------------------------------------+ |
+======================================================================================================================+
| QUICK AI: [Ask or tell AI about 17.5… (/ to focus)_____________________] [Send]  [⏸ Pause] [🔓 Unblock…] [⚡ Run…]   |
+======================================================================================================================+
```

### 5.4 Inbox Panel: "Process Inbox" Command & Note-Focused Contextual Chat (`T074` + `T076`)

```text
+======================================================================================================================+
| INBOX — TO ANALYZE (3 ready, 1 draft)            [+ New Note]  [✨ Process Inbox (3 ready)…]  [🗑 Discard Selected…] |
+======================================================================================================================+
| [x] N071 · [READY ▾] · 10m ago · from: owner · about: UI priority editing                                            |
|     "es. interfaccia per cambiare priorità: click sulla priorità corrente apre un menu per cambiarla"                |
|     [✨ Process & Chat]  [⚡ Quick Microtask]  [+ Task…]  [+ Use Case…]  [✓ Resolve…]  [⋯]                           |
+----------------------------------------------------------------------------------------------------------------------+
| [x] N072 · [READY ▾] · 5m ago · from: gcube_atlas · about: verification-queue filtering                              |
|     "verification-queue --for should also match session aliases when a workspace has multiple worktrees"             |
|     +--------------------------------------------------------------------------------------------------------------+ |
|     | 💬 PROCESS NOTE N072 — AI Triage & Contextual Chat                                                    [Hide] | |
|     | Suggested Triage Proposal: **Create Emergent Task** in `engine` (P2, executor: `kilo`, links `UC014`)        | |
|     |   Title: "verification-queue --for matches session aliases across worktrees"                                 | |
|     |   [✓ Accept & Create Task]   [Convert to Use Case Instead…]   [Mark Already Covered by T044]   [Discard]     | |
|     | ------------------------------------------------------------------------------------------------------------ | |
|     | [Ask or refine with AI: e.g. "Make it P1 and link to T070 instead"_________________________________] [Send]  | |
|     +--------------------------------------------------------------------------------------------------------------+ |
+======================================================================================================================+
```

---

## 6. Relationship to Initiative 17, T074, and T075 & Initiative 18 Plan

### 6.1 Clean Boundary with Initiative 17, `T074`, and `T075` (No Duplication)
- **Initiative 17 (`tasks/17-use-cases-drive-tasks/plan.md`)** already owns:
  - `17.1`–`17.2`: Bidirectional `use-cases` <-> `linked-tasks` projection and `tasks link` / `unlink` CLI.
  - `17.4`: `tasks new --from-use-case <UC###>`.
  - `17.5`–`17.6`: Use-case `approval` (`proposed` | `approved` | `deprecated`) vs. derived `stage` (`draft`, `planned`, `in development`, `ready`, `ready (revalidation pending)`, `verified`, `failing`, `partial`, `untested`) and `use-cases validate --force`.
  - `17.9`–`17.10`: Backend routes and UI components for use-case stage/approval and task <-> use-case linking.
- **`T074` (`tasks/specs/contextual-element-chat.md`)** has its own full specification and depends on `T073` (orchestrator control plane & session routing).
- **`T075` (`Valida e chiudi da UI`)** remains a narrow, immediately shippable slice (Validate & Close on `Delivered`/`Verified` column headers, card, and detail modal). Once the atomic batch close command (`18.1` below) lands in `tasks_engine.py`, `T075`'s bulk endpoint moves onto that atomic engine batch command instead of looping per task.
- **Initiative 18 (`tasks/18-owner-fast-interactions/plan.md`)** (or `19` if `T074`'s initiative claims `18` first) covers the **net-new engine, backend, Web UI, and VS Code extension slices** identified in this study without duplicating `17.*` or `T074`.

### 6.2 Proposed Initiative 18 Breakdown (Ordered, Right-Sized `S`/`M` Tasks)

| Task ID | Layer | Title & Scope | Size | Depends On | Priority |
| --- | --- | --- | --- | --- | --- |
| **18.1** | **Engine (`tasks_engine.py`)** | **Atomic batch `close`/`transition`, `set-next-up`, non-destructive `use-cases edit`, and owner-override audit marker** — (1) Add atomic multi-ID `tasks close <id1> <id2> ... [--verifier owner] [--reason <r>] [--dry-run] [--expect-plan-hash <h>]` that validates and transitions a list of `delivered`/`verified` tasks all-or-none under one `.ai-orch.lock`; (2) record explicit `[owner-override: verification-mode=<mode>]` in `## Log` when `--verifier owner` closes a task whose `verification-mode` is `cross-agent`/`panel` without a prior independent verification record; (3) add `tasks set-next-up <id> yes\|no [--dry-run] [--expect-task-hash <h>]`; (4) add non-destructive `tasks use-cases edit <UC###>` (`--title`, `--actor`, `--priority`, `--short`, `--description`, `--scenario`, `--verification-command`, `--expect-hash`) that preserves `## AI Validation Log`, `last-tested`, and `last-verdict`. | M | Owner answers `Q-A`..`Q-E` | **P1** |
| **18.2** | **Backend (`server.py`)** | **Upgrade `T075` bulk `validate-close` to atomic engine batch + expose missing task mutation endpoints** — Move `POST /api/tasks/validate-close` onto `18.1`'s atomic batch CLI (`expect_plan_hash`); add backend endpoints for `set-executor`, `set-verify-by`, `verification-queue`, `set-waiting-on`, `set-next-up`, `step list/add/check/uncheck`, `move --to-project`, `ship <NN>`, and `reopen --to delivered --verify-by`. Standardize `--actor owner` and provenance metadata (`via: web-ui`, `request_id`). | M | 18.1, T075 | **P1** |
| **18.3** | **Backend (`server.py`)** | **Use Case, Question, and Inbox missing endpoints** — Add backend routes for `use-cases edit` (non-destructive, from `18.1`), `use-cases record-validation` (owner manual `pass`\|`fail`\|`partial` verdict), `questions move --to <url>`, `questions answer` with `--apply-ref` and `--changes-result`, standalone `questions ask` (`--blocks -`), and `inbox to-use-case`. | S | 18.1 | **P1** |
| **18.4** | **Web UI (`frontend`)** | **Reusable `<InlineFieldPopover>`, Toast `[Undo]` / `[Reopen]` system, and 409 Conflict Banner** — Build the shared `<InlineFieldPopover>` primitive (2-click selection, optional inline reason input, keyboard `1`–`4` / `Enter` / `Esc`), the `<ActionToast>` manager (exact-inverse `[Undo]` using post-action `task_hash` vs. compensating `[Reopen]` for closures), and the non-retrying `409 Conflict` refetch+review banner. Amend `control-plane-safety.md` §2.1 for Category 1 single-field edits. | M | 18.2 | **P1** |
| **18.5** | **Web UI (`frontend`)** | **Inline-edit pills & restrained card quick actions across Kanban, Queue, Tree, Timeline, and Task Detail** — Wire `<InlineFieldPopover>` for `Priority`, `Executor`, `State` (leaf tasks only, legal transitions), `Size`, `Kind`, `Verify-by`, `Waiting-on`, `Labels`, and `Next-up ★` across `BacklogManager`, `TaskTreeView`, `TimelineCard` (replacing the 4-click full-screen diff modal for priority/size!), and `TaskDetailModal`. Add `[+ New Task…]` modal, interactive `## Steps` checkboxes in `TaskDetailModal`, and card `[⋯]` overflow menu. | M | 18.4 | **P1** |
| **18.6** | **Web UI (`frontend`)** | **Questions, Use Cases, and "Process Inbox" fast interactions** — (1) Render inline option radios + `[Answer & Unblock]` inside `TaskDetailModal` for open blocking questions; add `[+ Ask Question…]`, `Move to Tracker…`, and `Moved` filter to `DecisionsTab`; (2) make `Task T###` pills clickable in `UseCasesManager`/`UseCaseDetailModal`, add `Record Verdict…` and non-destructive `Edit UC`, and remove remaining `window.alert`/`window.confirm` calls; (3) add `[✨ Process Inbox]` on `InboxPanel` header and note rows (opening note-scoped triage + chat per `Q-F`), 1-click `draft`/`ready` pill toggle, and `+ Use Case` conversion. | M | 18.3, 18.4, T074 | **P2** |
| **18.7** | **VS Code Extension & Keyboard Shortcuts** | **Webview bridge parity, VS Code Sidebar TreeView inline/context commands, and board keyboard shortcuts** — (1) Register all `18.2`–`18.3` message types in `dashboard-panel.ts`; (2) add inline hover icons (`Validate & Close`, `Chat on Element`, `Validate Use Case`) and right-click QuickPick context menu commands (`Set Priority`, `Set Executor`, `Transition State`, `Reopen`) to `nextUpView`, `initiativesView`, `decisionsView`, and `useCasesView` in `package.json` & `extension.ts`; (3) wire single-key shortcuts (`v`, `p`, `e`, `s`, `l`, `u`, `c`, `Space`) when a card/row/modal is focused. | M | 18.5, 18.6 | **P2** |

---

## 7. Open Questions for the Owner

*(Note: The owner has already decided the guiding speed criterion, 2-click inline pill menus for short fields, and full tool access in contextual chat (`T074`). Only the remaining policy and edge-case questions are listed below.)*

### Q-A: Owner Closure When `verification-mode` is `cross-agent` or `panel` (Verifier Policy)
- **Context:** `task-and-state-model.md:125` states that `cross-agent` and `panel` tasks require an independent agent/panel verification record before closing, whereas `tasks_engine.py:8943` (`_is_independent_verifier`) allows `verifier: owner` to satisfy any verification mode, and `T075` closes delivered tasks as `verifier: owner`.
- **Options:**
  - **Option A (Allow Owner Closure Everywhere as an Explicit, Audited Owner Override — Recommended):** The owner can always `Validate & Close` any task (`--verifier owner`), regardless of `verification-mode` or `verify-by`. When the task's `verification-mode` is `cross-agent` or `panel` (or `verify-by` points to another workspace) and no prior verification was recorded, the UI shows a small warning badge on the button/dialog (`⚠ Override cross-agent`) and the engine records `verifier: owner (override: skipped cross-agent)` in `## Log`. Update `task-and-state-model.md` §3.1 to match.
  - **Option B (Block 1-Click Owner Closure on `cross-agent` / `panel` Tasks Unless Explicitly Forced in a Modal):** Refuse 1-click `Validate & Close` on tasks with `verification-mode: cross-agent` or `panel` unless an independent agent run has already marked them `verified`, or force a separate override modal.
- **Recommendation:** **Option A**. The owner is the ultimate authority when testing the product live; flagging the override in the UI badge and recording it explicitly in `## Log` preserves audit honesty without blocking the owner.

### Q-B: Reversibility & Toast Action Contract (`[Undo]` vs. `[Reopen]`)
- **Context:** Metadata edits (`priority`, `size`, `kind`, `executor`, `labels`, `use-cases`, `next-up`, `verify-by`, `step check`) have an exact inverse, whereas closing a task (`Validate & Close` -> `done`) moves the file to `tasks/done/` and writes audit log entries.
- **Options:**
  - **Option A (Show `[Undo]` Only for Exact Inverses; Show `[Reopen]` for Closures; No Button for Non-Reversible Transitions — Recommended):** Show `[Undo]` on the toast only when the exact previous state can be restored against the post-action `task_hash` (Category 1 edits). On task/note closures (`Validate & Close`, `Close`, `Drop`, `Discard`), label the toast button **`[Reopen]`** (which runs `tasks reopen <id> --to delivered` or `inbox reopen`). Do not show an undo button on `open -> in progress`, `questions answer`, or `record-validation`.
  - **Option B (Label Both Metadata Reverts and Task Reopens as `[Undo]`):** Use the label `[Undo]` even when the underlying action is `tasks reopen`.
- **Recommendation:** **Option A**. Calling `reopen` (which adds a reopen entry to `## Log`) `"Reopen"` rather than `"Undo"` is transparent about what happens in the git/task history.

### Q-C: Bulk Action Atomicity (`All-or-None` vs. `Best-Effort Partial`)
- **Context:** When the owner runs a bulk action from a column header (e.g. `Validate & Close (5)` on the `Delivered` column), one of the 5 tasks might fail a guard (e.g. a leftover template placeholder in `## Verification` per `T062`, or a concurrent edit).
- **Options:**
  - **Option A (Atomic `All-or-None` Engine Batch with Pre-Flight Guard Check in Preview — Recommended):** The preview step (`--dry-run`) checks all guards across the selected tasks, marks any ineligible task in red in the checklist dialog (auto-unchecking it with the reason shown), and computes one `plan_hash` for the eligible checked set. When the owner clicks `Confirm`, the engine applies all checked tasks **atomically (all-or-none)** under a single `.ai-orch.lock`.
  - **Option B (Best-Effort Loop with Per-Task Partial Results):** Loop task by task; commit whichever tasks succeed and show a summary of which ones failed.
- **Recommendation:** **Option A**. Surface guard failures in the preview checklist so the owner can uncheck the offending task before applying, and guarantee atomic all-or-none execution on apply.

### Q-D: Bulk Action Scope on Filtered Boards
- **Context:** The Kanban board or Queue may have active filters (project selector, search box, label filter, `Next-up only`).
- **Options:**
  - **Option A (Act on Currently Visible Filtered Cards, Frozen at Preview, with Per-Row Checkboxes in the Dialog — Recommended):** Clicking `[✓✓ Validate & Close (N)…]` on a column header captures the exact `N` tasks currently visible in that column, displays them with individual checkboxes (all checked by default) and a banner noting any active filter (`"3 of 7 delivered tasks shown (filtered by #ui)"`), and executes only on the checked IDs.
  - **Option B (Act on All Tasks in That State Across the Project Regardless of Active UI Filters):** Ignore active search/label filters when clicking the column header button.
- **Recommendation:** **Option A**. Acting on hidden cards that are filtered out of view is dangerous; freezing the visible list and providing checkboxes in the dialog gives the owner exact control.

### Q-E: Fast-Path Concurrency Check (`control-plane-safety.md` Amendment) & `409 Conflict` Handling
- **Context:** `control-plane-safety.md:147` currently requires a two-step `Preview` -> `ConfirmDialog` -> `Apply` flow for every write.
- **Options:**
  - **Option A (Amend `control-plane-safety.md` so Single-Field Exact-Inverse Edits Use the Loaded `task_hash` in 1 Round-Trip; Never Auto-Retry on `409` — Recommended):** Allow Category 1 single-field inline edits (`priority`, `size`, `kind`, `executor`, `labels`, `short`, `next-up`, `verify-by`, `waiting-on`, `step check`, `link`/`unlink`) to send the already-loaded `task_bundle_sha256` directly to the apply endpoint (1 round-trip + `[Undo]` toast). If the engine returns `409 Conflict`, **never auto-retry silently**—refetch the task and show an inline conflict banner so the owner can review the concurrent change.
  - **Option B (Keep Two-Step Preview Round-Trip Before Every Inline Pill Edit):** Run a background `--dry-run` HTTP call before every inline edit, or keep `ConfirmDialog`.
- **Recommendation:** **Option A**. Passing the loaded `task_bundle_sha256` preserves 100% of the optimistic concurrency guarantee (`409` if anything changed since render) while cutting latency in half.

### Q-F: "Process Inbox" Command Behavior
- **Context:** The owner asked for a UI command to process inbox notes (*"mi processi tutti gli inbox? anche per questo servirebbe un comando sull'interfaccia, che eventualmente apre una chat"*).
- **Options:**
  - **Option A (Unified `[✨ Process Inbox]` Command Opening Note-Focused Chat with AI Triage Proposal as the Suggested First Action — Recommended):**
    - On a **single note row** (`[✨ Process]`): opens the note's Contextual Chat drawer (`T074`) and immediately runs/displays the structured AI triage proposal (`Create Task`, `Create Use Case`, `Ask Question`, `Already Covered by <ID>`, or `Discard`) with 1-click `[Accept]` buttons **plus** the live chat input right below so the owner can either accept in 1 click or tell the AI *"make it P1 and link UC012"* in natural language.
    - On the **Inbox header** (`[✨ Process Inbox (N ready)]`): runs AI triage across all `ready` notes in the project/workspace and opens a stepping queue view where each note shows its proposal card + inline chat box (`[Accept & Next ->]`).
  - **Option B (Separate "Run Batch Triage" and "Open Chat" Commands):** Keep batch triage as a background job that only writes proposal JSON, separate from contextual chat.
- **Recommendation:** **Option A**. Combining the structured 1-click triage proposal with the note-scoped chat input in one surface matches the owner's exact workflow (*"process inbox, which optionally opens a chat"* when a note needs discussion or refinement).

### Q-G: Audit Wording for Token-Authenticated UI Mutations & VS Code Sidebar Click Behavior
- **Context:** (1) UI calls are authenticated by `X-AI-Orch-Token` / VS Code host and should record honest provenance; (2) clicking a task or use case in the VS Code sidebar (`Next Up`, `Initiatives`, `Use Cases`) currently opens the raw `.md` file instead of the Dashboard detail modal.
- **Options:**
  - **Option A (Record `owner (via web-ui | vscode-ext)` + `request_id` in Audit Logs; Click in VS Code Sidebar Opens Dashboard Detail Modal — Recommended):** Attribute UI mutations to `owner (via web-ui)` / `owner (via vscode-ext)` with `request_id` in the event ledger (never claiming hardware proof of a physical click), and make clicking a task/UC in the VS Code sidebar open its Detail Modal in the Dashboard Webview (keeping `Open Markdown File` as an inline `[$(go-to-file)]` icon).
  - **Option B (Record Plain `owner` Without Surface Tag; Keep VS Code Sidebar Click = Open Raw `.md` File):** Keep current behavior.
- **Recommendation:** **Option A**.
