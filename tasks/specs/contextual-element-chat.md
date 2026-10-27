# Spec — Contextual AI Chat on a Single Element (Task, Use Case, Question)

- **Status:** Draft v1 (2026-10-27), for owner review
- **Drives:** Initiative 18 (`tasks/18-contextual-element-chat/plan.md`, after approval)
- **Origin:** Owner request (2026-10-27, T074): *"mi servirebbe poter interagire con ia relativamente a una specifica use-case, task, o questione; nella vista elemento un box in cui mando un messaggio, o apro un pannello contestuale per chat"*
- **Related:** [`events-and-triggers`](events-and-triggers.md) (orchestrator turn queue, event ledger), [`agent-runs-from-ui`](agent-runs-from-ui.md) (`SupervisedInvocation`, tool adapters, `--resume`), [`use-cases-drive-tasks`](use-cases-drive-tasks.md) (Initiative 17: bidirectional task ↔ use-case links), `T073` (`orchestrator-control-plane-study.md`: broker/interactive session messaging and provenance guards), `T076` (fast owner UI interactions), `16.8` (workspace/console mail).
- **Repos:** `ai-orchestration` (core engine + CLI), `ai-orchestration-ui` (backend + React UI), `vscode-ai-orchestration` (extension bridge + webview)

---

## 0. Core Model (Owner Decision — Normative)

> *"così gli dico ad es. una modifica al volo, o ci ragiono sopra"*; *"ovviamente può generare modifiche"*; *"semplicemente l'IA ha tutti i tool a disposizione per interagire con gli elementi, cambia solo il contesto della conversazione"*.

1. **Full toolset, zero special "proposed-change" machinery:** A contextual chat session is a normal AI session with **all tools** (`ai-orch` CLI / broker MCP tools, file read/edit tools — the exact same toolset as an orchestration session). It reads, edits, transitions, links, and creates tasks, use cases, and questions directly. There is no special diff-staging or one-click proposal confirmation pipeline for element chat.
2. **Session permission mode governs:** Edits happen immediately as in any session, governed strictly by the answering session's configured permission policy (`orchestrate` policy, no `bypassPermissions` default, no cross-session permission laundering).
3. **Only the conversation context changes:** The conversation starts anchored to a specific element (`task`, `use_case`, or `question`) and its linked items, and remains bound to that element across follow-up turns.
4. **Two seamless interaction paces:**
   - **Quick edit on the fly** (*"change priority to P1 because…", "add a verification step for…", "link UC004"*): sent from a 1-line inline box in the element view; must complete in a few seconds.
   - **Open-ended reasoning** (*"is this use case split right?", "how does this interact with T073?"*): expanded into a contextual chat drawer/panel on the element, which can transition to concrete edits at any moment in the same thread.

---

## 1. Starting a Conversation from an Element View (UI & ASCII Mockups)

Every element detail view (`TaskDetailModal`, `UseCaseDetailModal`, and question cards in `DecisionsTab`) gets two coupled entry points:

1. **Quick Inline Chat Bar (always visible in the element footer/header):**
   - A single-line input (`Ask or tell AI about <ID>… (Enter to send)`) + `[Send]` + `[Chat (N) ^]` toggle button showing the message count `N` of the element's thread.
   - Sending from the quick bar immediately starts/resumes the element's thread, shows an inline streaming status pill (`AI is updating T074…` or the 1–2 line reply summary), and auto-expands the drawer if the reply is multi-paragraph or if the user clicks it.
   - Keyboard shortcut when an element view is open: `/` or `Cmd+K` focuses the inline chat box; `Shift+Enter` expands the drawer.
2. **Expandable Contextual Chat Panel (right-hand split drawer or collapsible bottom sheet inside the modal/card):**
   - Shows the full persistent thread for this element, inline event pills for mutations performed during each turn (`[Event: task.priority_changed P2 -> P1]`), a model/profile selector pill (defaults to the fast contextual profile, switchable to `deep-reasoning` mid-thread), and `[Open in General Chat ->]`.

### 1.1 Task Detail View (`TaskDetailModal.tsx`)

```text
+======================================================================================================+
| [T074] (Chat contestuale per elemento)  [OPEN] [P1] [methodology]  Executor: kilo          [Chat(3)] |
| Chat contestuale con l'IA su un singolo use case, task o domanda                                 [X] |
+------------------------------------------------------------------+-----------------------------------+
| METADATA & LINKS                                                 | CONTEXTUAL CHAT — T074      [_][X]|
| Priority: [P1 v]  State: [open v]  Depends on: T073              | Session: claude (sonnet-4-5) [v]  |
| Use cases: [UC028] [+ Link UC]     Spec: contextual-element-chat | [Open in General Chat ->]         |
|                                                                  |-----------------------------------|
| ## Goal                                                          | You                         15:02 |
| Dalla vista di un elemento il proprietario scrive un messaggio...| Link this task to UC028 and set   |
|                                                                  | verify-by to owner.               |
| ## Steps                                                         |                                   |
| - [x] Spec (Kilo, sola lettura sul codice...)                    | AI (claude) • 3.1s          15:02 |
| - [ ] Revisione Codex e dell'architetto                          | Done. Linked `UC028` and confirmed|
| - [ ] Piano in iniziativa dopo l'approvazione                    | `verify-by: owner` on `T074`.     |
|                                                                  |  +------------------------------+ |
| ## Verification                                                  |  | * task.updated: T074         | |
| - Spec in tasks/specs/contextual-element-chat.md...              |  |   use-cases: +UC028          | |
|                                                                  |  |   (hash: 8a1f.. -> 4c92..)   | |
| ## Task Runs (0)                                     [+ Run...]  |  +------------------------------+ |
|                                                                  |                                   |
|                                                                  | You                         15:04 |
|                                                                  | Should step 2 also include Gemini?|
+------------------------------------------------------------------+-----------------------------------+
| QUICK AI: [Add a step for VS Code bridge parity check________________________] [Send] [Hide Chat v] |
| Actions:  [Start Progress] [Ask Question] [Promote]                                          [Close] |
+======================================================================================================+
```

### 1.2 Use Case Detail View (`UseCaseDetailModal.tsx`)

```text
+======================================================================================================+
| [UC028] (Orchestrator role & handoff)  [STAGE: IN DEVELOPMENT] [APPROVED]  Actor: Owner    [Chat(1)] |
| Owner manages the orchestrator role, queue, and succession handoff                               [X] |
+------------------------------------------------------------------------------------------------------+
| Priority: P0 | Verification: integration_probe | Last Verdict: PASS | Revalidation: pending          |
| Linked Tasks (2): [T070 (in progress)] [T073 (open)] [+ Create Task from UC] [+ Link Task]           |
|                                                                                                      |
| ## Scenario / Interaction Steps                                                                      |
| 1. Owner inspects orchestrator status...                                                             |
| 2. Owner triggers handoff to interactive session...                                                  |
|                                                                                                      |
| ## Acceptance Criteria                                                                               |
| - Single generation bump N -> N+1; no phantom session IDs...                                         |
+------------------------------------------------------------------------------------------------------+
| CONTEXTUAL CHAT — UC028 (collapsed preview — 1 turn)                                  [Expand Chat ^]|
| Last (2m ago): You: "Add acceptance criterion for ROLE LOST banner" -> AI updated UC028 (hash e4b1..)|
+------------------------------------------------------------------------------------------------------+
| QUICK AI: [Create a task from step 2 of this use case________________________] [Send] [Validate UC]  |
+======================================================================================================+
```

### 1.3 Question View (`DecisionsTab.tsx` Card)

```text
+======================================================================================================+
| [Q011] (Approvazione vs stadio UC)  [OPEN]  Blocks: 17.5  Decider: owner  Recommended: A   [Chat(2)] |
| Separiamo l'approvazione di uno use case dal suo stadio derivato dai task?                           |
+------------------------------------------------------------------------------------------------------+
| ## Context: Nella nota N072 "draft" indicava sia "non ancora approvato" sia "senza task"...          |
| (o) Option A (Recommended): Due campi distinti (`approval` + `stage` derivato)                       |
| ( ) Option B: Un solo campo `status` con valore `approved-empty`                                     |
| Free text / notes: [_______________________________________________________________________________] |
+------------------------------------------------------------------------------------------------------+
| CONTEXTUAL CHAT — Q011                                                                [Collapse v]   |
| You (14:50): What happens to existing `status: failing` use cases under Option A?                    |
| AI  (14:50): Under Option A, `status: failing` migrates to `approval: approved` + `last-verdict:     |
|              fail`, and `stage` is derived from linked tasks (`draft` if none, `failing` if ready).  |
| QUICK AI: [Rewrite Option A consequence to mention last-verdict migration____] [Send] [Answer Q011]  |
+======================================================================================================+
```

---

## 2. Binding and Storage Architecture

### 2.1 Element Binding Identity

Every contextual thread is bound to a canonical **`ElementRef`**:

```json
{
  "workspace": "ai-coding-tools",
  "project": "ai-orchestration",
  "element_type": "task",
  "element_id": "T074",
  "qualified_id": "ai-coding-tools:ai-orchestration/T074"
}
```

- Supported `element_type` values: `task` (`T###`, `NN.T`, or initiative `NN`), `use_case` (`UC###`), `question` (`Q###`). (Inbox notes `N###` can use the exact same binding seamlessly.)
- One primary thread per `(project, element_type, element_id)` with deterministic `thread_id`: `el-<element_type>-<element_id>` (e.g. `el-task-T074`, `el-use_case-UC028`, `el-question-Q011`). The owner can optionally click `New Thread / Reset Context` on the element, which archives the old generation (`el-task-T074@1`) and starts a fresh provider session while keeping past turns viewable.
- Multi-project placement (`ui-multi-project.md`): the thread lives in the **element's own project root** (`state.project_root(project)`), never in an ambiguous cwd.

### 2.2 Where Threads Are Stored: Options & Justification

| Option | Location | Pros | Cons |
| --- | --- | --- | --- |
| **Option S1: Event ledger only** | `<project>/.ai-orchestration/events/` | Single append-only store. | Events are compact notifications, not full streaming transcripts (`events.jsonl` chunks would bloat with raw LLM token streams, and scanning all event chunks to load one element's chat history is slow). |
| **Option S2: Separate `.ai-orchestration/threads/` tree** | `<project>/.ai-orchestration/threads/<thread_id>/` | Clean per-element directory (`thread.json` + `turns/<seq>/`). | Duplicates the turn-storage reader in `server.py` (`api_get_orchestrator_conversation`), `dashboard-panel.ts`, and `OrchestratorChatPanel.tsx`; general chat would have to merge two stores to show/filter element turns. |
| **Option S3: Existing conversation store + per-element index (Recommended)** | Turns in `<project>/.ai-orchestration/orchestrator/turns/<turn_id>/` + thread state in `<project>/.ai-orchestration/orchestrator/threads/<thread_id>.json` | **Single turn format and reader** for both general chat and element chat; general chat filtering (`?element=T074` or `All / General / Element threads`) works out of the box; `threads/<thread_id>.json` holds the element's `provider_session_id` for fast `--resume` and `last_context_hash`. | Requires adding `thread_id` and `element_ref` fields to `turn.json` (backward-compatible). |

**Decision / Recommendation: Option S3 (Unified Turn Store + `orchestrator/threads/<thread_id>.json`).**
- Every contextual chat turn is stored as a normal turn record in `<project>/.ai-orchestration/orchestrator/turns/<turn_id>/turn.json` carrying:
  - `type: "element_chat"` (or `owner_chat` with `element_ref`),
  - `thread_id: "el-task-T074"`,
  - `element_ref: {workspace, project, element_type, element_id, qualified_id}`.
- Thread metadata (active `provider_session_id`, `tool`, `model`, `created_at`, `updated_at`, `turn_ids: []`, `last_bundle_hash`) lives in `<project>/.ai-orchestration/orchestrator/threads/el-task-T074.json`.
- **In the element view:** `GET /api/orchestrator/conversation?project=P&element_type=task&element_id=T074` returns only that element's turns.
- **In `OrchestratorChatPanel` (General Chat):** A filter bar at the top (`[All Turns] [General Only] [By Element: All | T074 | UC028 | Q011]`) lets the owner see element conversations inline with a clickable badge `[T074: Chat contestuale per elemento]` or filter down to a single element.

---

## 3. Initial Context Injected & Size Budget

When turn 1 of an element thread starts (or on a subsequent turn if the element or its links changed on disk since `last_bundle_hash`), the engine builds a structured context bundle. On follow-up turns (`--resume`) where `last_bundle_hash` is unchanged, **only the owner's new message** (plus a 1-line hash-unchanged note) is sent, keeping follow-up turns tiny and fast. If files changed externally between turns, only the **delta** is injected.

### 3.1 Context Bundle Composition (`ai-orch chat context --element <ID>`)

| Section | Content Injected per Element Type | Cap (Bytes / Tokens) |
| --- | --- | --- |
| **1. Role & Tool Contract** | Short system framing: workspace/project path, content language settings from `tasks/AGENTS.md` (`tasks=it, questions=it, use_cases=en`), instruction that `ai-orch` CLI / MCP tools are available for mutations, and current element `expect_hash`. | ~1.5 KiB (~400 tok) |
| **2. Primary Element File (Full)** | • **Task (`T###` / `NN.T`):** Full Markdown of `<category>/T###-*.md` (or folder `README.md` + `CONTEXT.md` + `PROGRESS.md`, or `plan.md` block + header).<br>• **Use Case (`UC###`):** Full `tasks/use_cases/UC###-*.md`.<br>• **Question (`Q###`):** Full `tasks/questions/Q###-*.md`. | Up to **16 KiB** (~4,000 tok) |
| **3. Linked Items (Summaries + Excerpts)** | • **For a Task:** Linked `use-cases` (`UC###`: title, stage, approval, scenario & acceptance criteria); `depends-on` and child tasks (id, short title, state, goal); blocking/linked `questions` (`Q###`: status, question, answer); referenced `specs/*.md` in `paths:` (TOC + matching section up to 8 KiB).<br>• **For a Use Case (Initiative 17):** All `linked-tasks` (`id`, `state`, `priority`, `executor`, `goal`, `verification`); referenced spec.<br>• **For a Question:** All tasks in `blocks:` (id, state, goal, relevant section) + `origin-run` summary if any. | Up to **16 KiB** (~4,000 tok) |
| **4. Recent Activity & Events** | Last 15 events from `events.jsonl` where `subject == element_id` or a linked ID, plus latest run status/verdict summary (`runs/*/run.json`) if the element is a task. | Up to **4 KiB** (~1,000 tok) |
| **Total Initial Context Budget** | **Hard ceiling: 40 KiB (~10,000 tokens)** | **≤ 40 KiB (~10k tok)** |

- **Why a 40 KiB (~10k token) ceiling:** Small enough that prompt prefill takes **< 1 second** on Claude Sonnet / Haiku, GPT-5.2, or Gemini Flash/Pro, and leaves full room for the model to read additional files on demand with its tools if the conversation goes deeper.
- **Untrusted content hygiene:** Any external peer note or third-party log excerpt inside the bundle is wrapped in `<untrusted-data nonce="...">` per `events-and-triggers.md` §0c E3; the owner's own prompt and local task spec are first-party context.

---

## 4. Which Session Answers: Options, Latency, Cost & Recommendation

The central architectural question in T074 is **who executes the turn** when the owner sends a message from an element view.

### 4.1 Comparison of the Three Options

| Dimension | Option A: Workspace Headless Orchestrator Queue (`orchestrator enqueue`) | Option B: Interactive Orchestrator Session via Broker (`T073` / `16.7`) | Option C: Dedicated Per-Element Session with `--resume` (`SupervisedInvocation`) |
| --- | --- | --- | --- |
| **How it works** | Enqueues a turn in `.ai-orchestration/orchestrator/queue/`; drained by `orchestrator serve` resuming the single workspace-wide orchestrator session. | Routes the message via broker/mailbox (+ optional `SendMessage` nudge) to the live interactive Claude/Kilo window holding the orchestrator role. | Spawns a dedicated headless session for thread `el-<type>-<id>` on turn 1 (`claude -p --session-id <uuid>`, `kilo run`, `codex exec`) and resumes **that thread's own `provider_session_id`** (`--resume`) on follow-up turns. |
| **Latency for quick edits** | **Slow / unpredictable (15–90s+):** blocked behind any running `event_batch` or long orchestrator turn; carries the entire workspace orchestrator's accumulated context (up to 150k tokens) on every turn. | **Variable (5s to ∞):** requires an interactive window to be open and idle; if the human or agent is mid-turn in that terminal, it blocks or requires manual attention. | **Fast (2–6s for quick edits):** zero queue contention with other elements or background event batches; starts with a clean ~5–10k token element context; prompt caching hits 100% on `--resume`. |
| **Context isolation & pollution** | **Poor:** 10 quick edits across 5 tasks pollute the main orchestrator's context window, accelerating `rotate_after_tokens` handoffs. | **Poor:** mixes element micro-edits into the main interactive terminal's reasoning stream. | **Excellent:** each element thread has a focused, self-contained context; the main orchestrator learns of changes cleanly via emitted `events.jsonl` events! |
| **Concurrency** | Serialized globally per workspace (1 turn at a time). | Serialized on the single interactive terminal. | **Parallel across different elements; serialized per element** (lock on `threads/el-<type>-<id>.lock` + `tasks/.ai-orch.lock` only during the sub-second file write). |
| **Tool & model choice** | Locked to the workspace orchestrator's heavy model (e.g. Opus). | Locked to the open terminal's model. | **Configurable contextual profile:** defaults to a fast, high-capability model (e.g. Claude Sonnet 4.5 / Codex / Gemini), switchable to `deep-reasoning` (Opus) in 1 click in the drawer. |
| **Cost per quick edit** | High (~100k+ cached input tokens per turn as workspace session grows). | Medium-High (shares large interactive context). | **Low (~5–10k tokens on turn 1; cached on turn 2+): ~$0.01–$0.03 per quick edit.** |

### 4.2 Recommendation: **Option C (Dedicated Per-Element Resumable Session) as Default, with 1-Click Escalation to Option A/B**

1. **Primary mechanism (Option C):**
   - Each element thread (`el-task-T074`, `el-use_case-UC028`, `el-question-Q011`) runs its own lightweight, resumable session via `SupervisedInvocation` (`scripts/orchestration_invoke.py`), storing its `provider_session_id` in `.ai-orchestration/orchestrator/threads/<thread_id>.json`.
   - **Immediate execution, no daemon prerequisite:** When the owner hits `Send` in the UI/VS Code (or runs `ai-orch chat send <ID> "<message>"`), the backend/CLI spawns the turn worker **immediately** under a per-thread lock (`threads/<thread_id>.lock`), without waiting on the workspace-wide `orchestrator/queue/` or requiring `orchestrator serve` to be running.
   - **Default model routing:** New config key `routing.default_contextual_chat` (or profile `contextual`, defaulting to `default_orchestrator` tool with a fast coding/orchestration model such as `claude-sonnet-4-5` when available, overridable per turn in the UI header to `deep-reasoning` / `opus`, `kilo`, or `codex`).
   - **Latency target:**
     - First token streamed to UI: **< 1.5 s**.
     - Complete quick edit (e.g. `ai-orch tasks set` / header edit / step edit): **2–6 s end-to-end**.
2. **Bridge to the Workspace Orchestrator (Option A / Option B escalation):**
   - Because every mutation made by the element chat session goes through `ai-orch` (or emits file/event changes), the workspace orchestrator automatically sees the resulting events (`task.updated`, `task.transitioned`, `use_case.links_changed`, `question.answered`).
   - If a discussion in an element thread reaches a workspace-wide architectural decision (e.g., *"re-plan Initiative 17 around this"*), the drawer header offers **`[Hand off to Workspace Orchestrator]`**, which posts a summary turn (`orchestrator.ask` or console mail per T073) to the main orchestrator.

---

## 5. After the AI Changes Something: Live Refresh, Diff Summary & Undo

Because the contextual AI uses standard `ai-orch` commands and file edits, the existing reactive pipeline works with minimal additions:

1. **Pre-turn & Post-turn Snapshot (`element_snapshot`):**
   - Before invoking the agent turn, the turn wrapper records `pre_turn_event_seq` (the current workspace `events.jsonl` counter) and `pre_turn_hashes` of the element file and `tasks/00-INDEX.md`.
   - When the turn finishes (or as events are emitted mid-turn), the wrapper collects:
     - All `events.jsonl` entries emitted with `origin_session == thread_id` (or between `pre_turn_event_seq` and `post_turn_event_seq`),
     - Any direct file diff (`git diff` / pre-image vs post-image) on `tasks/` files touched during the turn (if the agent edited Markdown prose directly with `Edit`/`Write` instead of an `ai-orch` subcommand). If a direct edit touched `tasks/` without emitting an event, the turn wrapper runs `ai-orch tasks sync-index --apply` (if index fields changed), validates the touched file (`ai-orch tasks validate`), and emits a `task.updated` / `use_case.updated` / `question.updated` event with `before_hash`, `after_hash`, and a compact diff summary.
2. **Automatic Live Refresh of the Element View:**
   - The UI backend file watcher and event stream (`state.check_and_push_events()`) already broadcast `{type: "changed", project, areas: ["tasks", "use_cases", "questions", "orchestrator"]}` and `{type: "event", event}` over the WebSocket (and `panel.postMessage` in VS Code).
   - `TaskDetailModal`, `UseCaseDetailModal`, and `DecisionsTab` subscribe to these events: whenever the open element's `hash` changes or a turn finishes, the view re-fetches `getTaskDetail` / `getUseCases` / `getQuestions` in place **without closing the modal or losing scroll/chat state**, briefly highlighting changed fields.
3. **Inline "What Changed" Pills in the Chat Thread:**
   - Each assistant turn in `turn.json` stores `changes: [{element_id, file_path, event_type, summary, before_hash, after_hash, diff_stat}]`.
   - The chat bubble renders a compact, expandable change card right under the assistant's reply (e.g., `* Updated T074: priority P2 -> P1, added 1 step [View Diff] [Undo]`).
4. **Undo = Standard Engine / Git Mechanism:**
   - Before each contextual chat turn runs, the turn directory `<project>/.ai-orchestration/orchestrator/turns/<turn_id>/pre_images/` saves a lightweight copy of the primary element file (and `00-INDEX.md` if touched).
   - Clicking **`[Undo Turn Changes]`** on a turn (or running `ai-orch chat undo <turn_id>`) checks that the current file hash still matches `after_hash` (CAS guard so later edits are never clobbered), restores the `pre_images`, runs `sync-index`, and emits an `element.undo_applied` event. Beyond single-turn undo, normal `git diff` / `git checkout` works as usual since all `tasks/` files are plain tracked Markdown.

---

## 6. Permissions and Audit Trail

### 6.1 Permission Model (No Bypass, No Laundering)

- **Origin is always the authenticated human Owner:** Contextual chat turns can only be started from the authenticated UI (`X-AI-Orch-Token`), the VS Code extension webview bridge, or the local CLI (`ai-orch chat send`). Unattended trigger rules (`event_batch`) and external peer workspaces (`mail.send`) **cannot** enqueue contextual element chat turns.
- **Session permission policy:**
  - Contextual chat turns run under the **`orchestrate`** permission policy (`events-and-triggers.md` §0, `agent-runs-from-ui.md` §5.7):
    - Allowed: `ai-orch` CLI / broker MCP tools, reading workspace files, editing files under `tasks/` (and project docs/specs when asked).
    - **Never defaults to `bypassPermissions` / `--dangerously-skip-permissions`.**
    - Destructive operations (dropping a task, deleting files outside `tasks/`, modifying global config, `git reset`) still require an explicit UI confirmation modal (`confirm_token` / `expect_hash`), never executed silently by a chat turn.
- **Concurrency & CAS safety:**
  - While an element chat turn is running, if the owner simultaneously clicks a manual UI button on the same element (e.g. changing priority via dropdown), `tasks/.ai-orch.lock` serializes the writes and `expect_hash` prevents lost updates.

### 6.2 Audit Events (`events.jsonl`)

Every message and every mutation is recorded in `<project>/.ai-orchestration/events/` with full attribution:

| Event Type | `subject` | `origin_session` | `actor` | `data` Payload |
| --- | --- | --- | --- | --- |
| `chat.turn_queued` | `<element_id>` (e.g. `T074`) | `el-task-T074` | `owner` | `{turn_id, thread_id, element_ref, message_preview}` |
| `chat.turn_started` | `<element_id>` | `el-task-T074` | `<tool>:<model>` | `{turn_id, thread_id, provider_session_id, pid}` |
| `task.transitioned` / `task.updated` / `use_case.updated` / `question.updated` | `<target_id>` | `el-task-T074` | `<tool>:<model> (via owner chat turn <turn_id>)` | `{turn_id, thread_id, fields_changed, before_hash, after_hash}` |
| `chat.turn_finished` | `<element_id>` | `el-task-T074` | `<tool>:<model>` | `{turn_id, thread_id, duration_seconds, usage, changes_count, changed_ids: []}` |
| `chat.turn_undone` | `<element_id>` | `el-task-T074` | `owner` | `{turn_id, restored_files: [], after_hash}` |

In the element's `## Log` (for tasks) or history view, mutations performed by contextual chat carry the attribution `- YYYY-MM-DD, <tool> (chat #<turn_id>): <summary>`.

---

## 7. Web UI and VS Code Extension Parity

Following the established architecture (`ui-multi-project.md` §4 and `agent-runs-from-ui.md` §8), all logic lives in the Python engine (`ai-orch chat ...`), and the React frontend is shared 100% between the browser and the VS Code webview:

| Layer | Web UI (`ai-orchestration-ui`) | VS Code Extension (`vscode-ai-orchestration`) |
| --- | --- | --- |
| **Core Engine CLI** | `ai-orch chat send`, `ai-orch chat history`, `ai-orch chat context`, `ai-orch chat undo`, `ai-orch chat reset` | Same `ai-orch chat ... --json` commands invoked via `panel.cliClient` |
| **Transport / API (`api.ts`)** |• `POST /api/chat/element` (`{project, element_type, element_id, message, model?, profile?}`)<br>• `GET /api/chat/element?project=&element_type=&element_id=`<br>• `POST /api/chat/element/undo` (`{project, turn_id, expect_hash}`)<br>• `POST /api/chat/element/reset` (`{project, element_type, element_id}`)<br>• `GET /api/orchestrator/conversation?project=&element_id=` | Matching bridge handlers in `src/views/dashboard-panel.ts`:<br>• `postElementChat`<br>• `getElementChat`<br>• `undoElementChatTurn`<br>• `resetElementChat`<br>• `getOrchestratorConversation` (extended with `element_id` filter) |
| **Streaming & Refresh** | WebSocket pushes `turn_started`, `turn_output` (or 1s poll while active), `turn_finished`, and `changed` (`areas: ["tasks", "use_cases", "questions", "orchestrator"]`). | Extension file watcher on `.ai-orchestration/orchestrator/turns/` and `events/manifest.json` posts the exact same message payloads to the webview. |
| **Shared React Components** | Reusable `<ElementChatBar />` + `<ElementChatDrawer />` embedded in:<br>1. `TaskDetailModal.tsx`<br>2. `UseCaseDetailModal.tsx`<br>3. `DecisionsTab.tsx` (question cards)<br>4. `OrchestratorChatPanel.tsx` (thread filter chips + deep links back to the element modal) | Identical React bundle rendered inside the VS Code Dashboard Webview; plus a right-click context action **"Chat with AI on Item…"** on tree items in the VS Code sidebar (*Next Up*, *Initiatives*, *Use Cases*, *Decisions*) that opens the dashboard modal with the chat box focused. |

---

## 8. Implementation Plan (Proposed Initiative 18) & Open Questions

### 8.1 Proposed Initiative Breakdown (`18-contextual-element-chat`)

Each task is sized for one commit and one verification gate:

| Task | Title | Repo(s) | Depends on | Size |
| --- | --- | --- | --- | --- |
| **18.1** | **Engine: contextual bundle builder (`ai-orch chat context`) and per-element thread store** — Build the ≤ 40 KiB context bundle for `task`, `use_case` (including Initiative 17 links), and `question`; create `.ai-orchestration/orchestrator/threads/<thread_id>.json` and delta detection via `last_bundle_hash`. | `ai-orchestration/` | 17.1 | M |
| **18.2** | **Engine: dedicated resumable turn runner (`ai-orch chat send | history | undo | reset`)** — Execute element chat turns via `SupervisedInvocation` with `--resume <provider_session_id>`, per-thread lock, pre-image capture, post-turn validation/sync-index on direct file edits, diff summary extraction, and `chat.*` audit events. | `ai-orchestration/` | 18.1 | M |
| **18.3** | **UI Backend: `/api/chat/element` endpoints, conversation filtering, and WebSocket turn streaming** — Add REST endpoints in `ai-orchestration-ui/backend/server.py`, extend `/api/orchestrator/conversation` with `element_type`/`element_id` filtering, and wire WebSocket notifications. | `ai-orchestration-ui/` | 18.2 | S |
| **18.4** | **Web UI: `<ElementChatBar />` and `<ElementChatDrawer />` in Task, Use Case, and Question views + General Chat filter** — Embed the quick inline bar and expandable drawer in `TaskDetailModal`, `UseCaseDetailModal`, and `DecisionsTab`; render inline change cards with `[View Diff]` and `[Undo]`; add element filter bar in `OrchestratorChatPanel`. | `ai-orchestration-ui/` | 18.3 | M |
| **18.5** | **VS Code Extension: bridge handlers and sidebar "Chat with AI on Item…" action** — Add `postElementChat`, `getElementChat`, `undoElementChatTurn`, `resetElementChat` in `dashboard-panel.ts`, sync the webview bundle, add sidebar tree context-menu entry, and update bridge parity tests. | `vscode-ai-orchestration/` | 18.4 | S |

---

### 8.2 Open Questions for the Owner

#### Q-1: Who answers by default (Session Architecture)?
- **Options:**
  - **Option A (Dedicated per-element resumable session via `--resume` — Recommended):** Each element thread spawns its own lightweight headless session on turn 1 (~5–10k token context) and resumes that exact session on follow-up turns. Runs immediately without waiting on the workspace-wide orchestrator queue; includes a 1-click `[Hand off to Workspace Orchestrator]` button when a discussion grows into a workspace-level plan.
  - **Option B (Shared workspace headless orchestrator queue):** Every element message is enqueued as an `owner_chat` turn on the single workspace orchestrator session, with the element context prepended.
  - **Option C (Route to live interactive orchestrator console via broker):** Sends the message to the open interactive terminal (T073), falling back to Option A/B when no interactive session is active.
- **Recommendation:** **Option A**, because quick edits must complete in 2–6 seconds without blocking behind background turns or paying for (and polluting) a 100k+ token workspace-wide orchestrator session.

#### Q-2: Default Tool & Model Profile for Contextual Element Chat
- **Options:**
  - **Option A (Fast coding/orchestration model by default + 1-click switch in drawer — Recommended):** Default contextual chat to the workspace's orchestrator tool using a fast, low-latency model profile (e.g. `claude-sonnet-4-5` for Claude, `gpt-5.2-codex` for Codex, `gemini-4-argon` / Flash for Kilo), with a model/profile selector pill in the chat drawer to switch to `deep-reasoning` (e.g. `claude-opus-5-5`) whenever deeper architectural reasoning is needed.
  - **Option B (Always use the `orchestration` / `deep-reasoning` model configured for the workspace orchestrator):** Always use the exact same model as the main orchestrator (e.g. Opus), trading 2–3x higher latency and cost on quick edits for maximum reasoning depth on every message.
- **Recommendation:** **Option A**, matching the owner's primary criterion (*"modifica al volo, rapida, pochi secondi"* while still supporting deep discussion on demand).

#### Q-3: Scope of Direct File Edits Allowed in Contextual Element Chat
- **Options:**
  - **Option A (`tasks/` tree + linked specs/docs by default; code changes via normal task runs — Recommended):** The contextual chat session has all `ai-orch` tools and file read/edit tools for `tasks/**` and documentation/specs (`docs/**`), so it can freely edit any task, use case, question, initiative plan, or spec; if the owner asks to modify application source code, it either creates/updates a task and offers `[Launch Execute Run]` or asks confirmation before editing source files in the main working tree.
  - **Option B (Unrestricted workspace-wide file edits under the session's `acceptEdits` / `workspace-write` policy):** Allow the element chat session to edit application source code directly in the main workspace tree whenever asked.
- **Recommendation:** **Option A** (or Option B with a soft prompt in the system instructions to prefer `tasks/` and `specs/` unless the owner explicitly asks for a source code edit), keeping the main working tree clean for worktree-isolated `execute` runs while never restricting the owner when an immediate edit is explicitly requested.
