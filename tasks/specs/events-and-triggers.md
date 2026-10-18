# Spec: Events, orchestration sessions and triggers

- **Status:** draft for review (2026-10-17)
- **Drives:** initiative [12](../12-events-and-triggers/plan.md)
- **Origin:** owner request (2026-10-17). Interactions in the UI (answering a question, marking a note ready, a run finishing) change files, but nothing reacts to them until an orchestrator happens to look. The system needs explicit events and a reference to the orchestration session that must react.
- **Supersedes:** spec 08 §5 "Answer and resume run" (task 08.6 becomes a trigger rule here). It also closes the gap "answered but not yet applied".

## 0. Amendment (owner decision, 2026-10-17; normative, overrides §2 and §4)

**The orchestrator is always headless, even when the owner chats with it.**

- **One persistent orchestrator session per workspace.**
  - `ai-orch orchestrator start --tool claude|kilo|codex [--model M]` creates it. For Claude it pre-assigns a session UUID with `--session-id`; for Kilo and Codex it captures the id on the first turn.
  - It registers the session (§2, `kind: headless`, role `orchestrator`) and stores it in `<workspace>/.ai-orchestration/orchestrator.json`.
  - `orchestrator stop`, `orchestrator pause` and `orchestrator resume` control it.
- **Every stimulus is a turn.** An owner chat message or a batch of events becomes one turn: a resumption of the same session (`claude -p --resume <uuid> --output-format stream-json`, `kilo run -s <id> --format json`, `codex exec resume <id> --json`). Turns use the `orchestrate` permission policy (spec 07, 07.12 defaults, which include the kilo-mcp tools).
- **A durable, serialized turn queue.**
  - Turn requests live in `<workspace>/.ai-orchestration/orchestrator/queue/<seq>.json`.
  - One worker, under a lock, drains the queue. **Never two resumptions of the same session at the same time.**
  - Events that arrive while a turn runs are coalesced into the next turn as one batch.
  - Owner messages take priority over event batches.
  - A crashed turn is retried once, then reported.
- **Transcript.** Each turn stores its input, the streamed output (assistant text, tool calls, results) and its cost/usage under `orchestrator/turns/<seq>/`. The chat UI renders it.
- **Owner chat in the UI.** A chat panel shows the transcript and has an input box: a message → enqueue → streamed reply over the WebSocket. The owner can cancel the current turn, pause the session, and see queued items.
- **Event turns are rate-limited** (default: at most 6 per hour, configurable) and respect the trigger kill switch. While the session is paused, events accumulate and are delivered as one batch on resume.
- **§4 delivery changes:** the interactive-session channels (Monitor, hooks) are no longer part of the design. Every orchestration session is headless and is reached by resumption. Interactive tools (for example a Claude Code window) may still read `ai-orch events tail` manually, but nothing depends on it.
- **Role vs session; succession.** The **orchestrator role** owns the turn queue, the event cursor, the subscriptions and the transcript. The **tool session** currently holding the role is replaceable.
  - `orchestrator.json` records `generation` and `current: {tool, session_id, started, turns, last_usage}`; `sessions/<id>.json` keeps every past generation with `retired: {at, reason}`.
  - A new generation is started when:
    - a resumption fails irrecoverably (the session is not found, or there are 2 consecutive turn failures);
    - the context grows past a configurable threshold (`[orchestrator] rotate_after_tokens`, using the usage reported per turn; spec §0 12.1 facts);
    - the owner asks for it (`orchestrator rotate`).
  - The new session **registers itself**: it gets a new id and generation N+1, the old one is marked retired with the reason, and an event `orchestrator.rotated` is emitted.
  - The new session's **first turn is a handoff prompt** generated from files only, never from the dead session:
    - the role instructions;
    - the `tasks/00-INDEX.md` summary;
    - open questions and answered questions awaiting application;
    - active runs and their states;
    - events after the role cursor;
    - a summary of the last N turns, taken from the transcripts (the stored assistant texts, truncated);
    - the pending queue.

    After the handoff turn, the queue resumes from where it stopped.
  - **References survive succession:** `origin-session` on questions, runs and notes points to the **role** (`orchestrator`), not to a tool session id, so `resume-origin` always reaches the current generation.
- **`origin-session`** on questions, runs and notes is `orchestrator` (the role) when the orchestrator created them. `resume-origin` therefore means "enqueue a turn for the orchestrator", or "continue the run" when the origin is a run.

## 0a. Amendment: who brings the orchestrator to life (owner decision, 2026-10-18; normative)

Found on 2026-10-18: no workspace had an orchestrator. `orchestrator start` registers the role but nothing drains the
queue (only a manual `run-next`), and in practice the "orchestrators" were interactive sessions the owner opened, which
the engine does not know about. Decisions:

- **The role stays headless**, one per workspace (§0 unchanged). It is never blocked by interactive conversations:
  interactive sessions are **consoles**. They talk to the role asynchronously (`orchestrator enqueue`, peer mail,
  questions) and never hold its lock or wait on its turns; the role never waits on them.
- **A worker drains the queue on its own.** `ai-orch orchestrator serve` is a long-running, single-instance worker
  (pid file + lock under `.ai-orchestration/orchestrator/`, heartbeat in `orchestrator.json`) that runs `run-next`
  whenever the queue is not empty and the role is not paused, respecting the §0 rate limits and the trigger kill switch.
  It also runs the trigger evaluation that `triggers daemon` does today, so one process per workspace is enough. It exits
  cleanly on `orchestrator stop`; a stale pid (process gone, heartbeat older than a threshold) is reported by `status`
  and the Doctor.
- **`ai-orch orchestrator ensure`** (idempotent, preview → apply with a hash, like every write) brings a workspace to a
  working orchestrator:
  1. no project config → runs the setup engine (§0b) with the defaults from the global config (today: Claude as
     orchestrator) and shows the diff;
  2. role not started → `start`;
  3. worker not running → starts `serve` detached;
  4. prints what it did and the role's status.
  `--dry-run` prints the plan without writing; `--check` exits non-zero when anything is missing (for hooks and the UI).
- **Any session instructs it.** The orchestration skills (generic template and bindings) tell every session: when the
  owner asks to use the task mechanism, or when a task-related command finds no orchestrator, run
  `orchestrator ensure --dry-run`, show the plan in one line, and apply it unless it would write global config (that
  needs the owner's yes). Sessions do not become orchestrators themselves.
- **A standard interaction session (optional, later):** a predefined interactive console per workspace (for example a
  Claude Code window started with a role prompt), registered as `kind: interactive, role: console`, which shows the
  orchestrator's transcript and relays the owner's messages. Not required for the mechanism to work.
- The UI and the VS Code extension show "orchestrator: missing / stopped / running (worker alive) / paused" and offer
  "Ensure" with the preview.

## 0b. Orchestrator configuration and reassignment (owner request, 2026-10-17; normative)

- **`routing.default_orchestrator` names the tool that holds the orchestrator role**, and `routing.default_executor` the default executor that the orchestrator delegates to. The Config tab shows them in an "Orchestrator" card, together with the current role holder: tool, generation, session id, turns, last usage, and status (`active`, `paused`, `rotating`).
- **Reassigning the orchestrator** (changing `default_orchestrator`, or "Reassign…" in the card) is a succession with a tool change:
  - **Preview:** shows the config diff and the plan "generation N (claude) → N+1 (kilo), with a handoff turn"; the plan has a hash.
  - **Confirm:** writes the config, then rotates the role (§0 succession), with the reason `reassigned`.
  - The queue and the cursor carry over; the old session is retired.
- **First-run setup (wizard)** runs when the workspace has no project config, or on demand. The UI version and the CLI version (`ai-orch setup`) share one engine with the `orchestration-setup` skill. The steps:
  1. detect the installed tools, with their versions and auth status;
  2. choose the orchestrator tool and the default executor;
  3. choose the verification mode and the cross-agent order;
  4. choose models per profile, prefilled from the global config;
  5. choose the scope: project-local (`.ai-orchestration.local.toml`) or global;
  6. choose the permission policy, showing the Q001 defaults;
  7. preview the whole config diff → apply → optionally start the orchestrator.

  Every write goes through preview → confirm with hashes.
- `orchestrator start` refuses when the routing points to a tool that is not enabled or not installed, and the error names the setup command.

## 0c. Amendments after the Codex review (2026-10-17; normative, override the sections they name)

- **E1 — events use an outbox, not "iff" (§1).**
  - **Write path:** each mutation first writes an outbox record `prepared` (mutation id, intended changes, event payload), applies its file changes (each file carrying the mutation id where the format allows), then marks the record `committed`. Readers only see committed events.
  - **Recovery:** startup reconciliation commits a `prepared` record whose changes are fully applied, or rolls it back (it restores the pre-images stored in the record) when they are not.
  - **Locking:** one workspace event lock with one durable counter serves every producer (tasks, runs, config). The lock order is task lock → run lock → event lock.
- **E2 — the cursor belongs to the role; deliveries are batches (§0, §2).**
  - The role cursor lives in `orchestrator.json`. Each delivery is an immutable batch: an id, a list of event ids, and a state `pending`, `running`, `acknowledged` or `dead`.
  - The cursor advances only after the turn's transcript is durably stored. A retry reuses the same batch id.
  - Agent-triggered core mutations carry an idempotency key (`batch_id:n`), and the core refuses a repeated key.
  - Succession inherits the outstanding batches; it does not rebuild them from the cursor.
- **E3 — unattended turns run with reduced capabilities (§0, §5).**
  - Event-batch turns (not owner chat turns) get a **read-mostly policy**: file read, `ai-orch` read commands, and `ai-orch questions ask` and `notify`.
  - Delegation (kilo-mcp `implement`), shell, config changes, task transitions and writes are **not** allowed. The turn proposes them as actions that the owner confirms in the UI (one click; the proposed action is recorded with its hash).
  - Owner chat turns use the `orchestrate` policy.
  - **Untrusted content:** every piece of file or event content placed in a prompt is wrapped as quoted, typed data with its provenance, under an explicit instruction that it is data, not instructions.
- **E4 — a turn is not a run (§0).** Turns are their own record type (`orchestrator/turns/<turn_id>/`). A shared **supervised-invocation primitive** (adapters, process groups, logging, cancel) is extracted from `orchestration_runs.py`; runs and turns wrap it with their own validation and lifecycle.
- **E5 — every turn has bounds.** A wall-clock timeout (default 15 min), an output/log cap, a provider budget where the CLI supports one, and a tool-call budget enforced by the supervisor. A turn that hits a bound is killed (whole process group) and moved to `dead`, which is visible in the UI.
- **E6 — the queue protocol.**
  - Enqueue is atomic (temp file + rename).
  - Each item has a lifecycle state `queued`, `claimed`, `running`, `done`, `failed` or `dead`, a worker lease with stale-claim recovery, and a persisted retry count.
  - Owner messages take priority, but at least one event batch runs after every 3 owner turns.
  - Owner cancellation moves the item to `cancelled`.
- **E7 — trigger state per (rule, event).** The state is `pending`, `fired`, `skipped`, `retry` or `dead`, and every firing has a deterministic firing id. The scan watermark advances only when every applicable rule has reached a terminal state. The daemon is a singleton (lock and lease). Rate limits are persisted token buckets (one for agent launches, a separate one for notifications), and deferred items carry `not_before`.
- **E8 — rotation measures context explicitly.** 12.1 normalizes provider usage into `input_tokens`, `cache_read`, `cache_write`, `output_tokens` and `estimated_context_tokens`. Rotation uses the estimated current context (or an explicit compaction signal), never a sum of per-turn inputs. Cost is tracked separately.
- **E9 — succession is fenced.** Under the orchestrator lock the role goes `active → rotating → active`, with a generation fencing token. The new session is created and its handoff completed **before** it becomes current; the old one is retired afterwards. If the bootstrap fails, the rotation rolls back. Output carrying a stale generation token is rejected.
- **E10 — identifiers.**
  - Four distinct ids: `role_id` (`orchestrator`), `generation`, `registry_session_id` and `provider_session_id`.
  - `origin-session` is added explicitly to the question header (after `origin-run`), to the inbox note header (after `processed-by`) and to `run.json`. When both an origin run and an origin role exist, the run takes precedence for `resume-origin`.
  - `config.changed` covers the project config only; a global config change is announced per workspace when the next turn reads it.
- **E11 — the application ledger.** Applying an answer is recorded in an append-only ledger, `tasks/questions/applied.jsonl` (`{question, by, at, ref}`), not inside `## Answer`, so spec 08's answer grammar does not change. Questions never move (spec 11 S3); this also fixes 11.4.
- **E12 — the UI streaming contract.** There are three authenticated WebSocket message families: domain events (`event`, with `seq`), queue state (`queue`), and turn output (`turn_output`, with a monotonic per-turn offset). On reconnect the client replays from its last `seq` and offset. Turn output is persisted before the turn is acknowledged.
- **E13 — readers use the core.** The event log is read through `ai-orch events tail`, which uses a chunk manifest updated under the event lock and tolerates a truncated final line. The extension watches the manifest, not one file.

## 1. Events (core)

**Log.** The core appends every relevant fact to `<workspace>/.ai-orchestration/events.jsonl`:

- each line is one JSON event: `{seq, id, ts, type, subject, data, origin_session, actor}`;
- `seq` is monotonic per workspace and allocated under the task-write lock;
- `id` is a UUID used for deduplication;
- the log is append-only and rotates like run logs (spec 07 R9): immutable chunks, logical offsets.

**Event types** (`subject` is the id of the task, question, run or note):

| Type | When |
| --- | --- |
| `question.asked` | a question is filed |
| `question.answered` | a question is answered |
| `question.withdrawn` | a question is withdrawn |
| `question.applied` | an answer has been acted upon (§3) |
| `task.transitioned` | any state change; `data` holds `from`, `to`, `actor` |
| `run.started` | a run starts |
| `run.finished` | a run ends; `data` holds `status`, `verdict?` and `questions?` |
| `note.ready` | an inbox note becomes ready |
| `note.processed` | an inbox note is processed or discarded |
| `config.changed` | the config changes |

**Emission** happens inside the same locked operation as the state change, so an event exists if and only if its change was applied. The UI backend and the VS Code extension never emit events themselves; they call the CLI.

**Reading:**

- `ai-orch events tail [--since SEQ] [--type T...] [--session S] [--follow] --json`;
- the UI backend's WebSocket forwards the events (this replaces the coarse `{type:"changed"}`);
- the extension watches the log file.

## 2. Orchestration sessions

**Registry:** `<workspace>/.ai-orchestration/sessions/<session_id>.json`, holding:

- `session_id`, `tool` (`claude`, `kilo`, `codex`, `human`), `kind` (`interactive`, `headless`);
- `resume` (the tool session id and cwd, for headless sessions);
- `last_seen`, `cursor` (the last event `seq` the session has handled), `subscriptions` (event types and subjects).

**Commands:**

- `ai-orch session register --tool T --kind K [--resume-id ID] [--subscribe TYPE...] --json` returns `session_id`;
- `session heartbeat`, `session ack --seq N` (advances the cursor), `session list`, `session end`.

**Origin linkage:**

- Questions, runs and inbox notes record `origin-session` when they are created by a registered session.
- Questions get a new header field `origin-session` (`-` when absent), added to spec 08's header after `origin-run`.
- Runs started by a session record it in `run.json`.

**Pending work for a session** = events after its cursor that match its subscriptions, or whose subject has `origin-session` = this session.

## 3. "Applied" — closing the loop on answers

- A question in state `answered` is **pending application** until `questions apply Q### --by WHO --ref TEXT`. The command sets `applied-by`, `applied` and `applied-ref` (a task id, a commit or a config change) in `## Answer`, and emits `question.applied`.
- The Decisions tab shows a third group, "Answered, awaiting application", between Open and History.
- The owner sees when an answer has been acted upon, and the orchestrator cannot silently forget one.

## 4. Delivery to sessions

| Session kind | How it receives events |
| --- | --- |
| **interactive Claude Code** | **Pull, two channels.** (a) While the session is working, it keeps a Monitor on `ai-orch events tail --follow --session <id>`. (b) Between turns, a Claude Code hook injects the pending events into the next prompt's context. The exact hook mechanism must be verified against Claude Code's documentation (12.1 starts with that check); if no hook can add context, (b) becomes a status-line or notification reminder instead. |
| **interactive Kilo / Codex** | Pull through the same CLI. The binding skills instruct the agent to check `session pending` at each phase boundary. |
| **headless** (an `orchestrate` run, or any session registered with `resume`) | **Push by resumption.** The trigger engine starts a continuation (spec 07 `--continue`, or the tool's resume command) with the event rendered as instructions. |
| **human** | The UI notification area, plus the Decisions and Runs badges. |

## 5. Trigger rules

**Configuration** lives in `orchestration.toml` (project or global):

```toml
[[triggers]]
name = "resume-run-on-answer"
on = "question.answered"
when = { origin_run = "*" }              # field matchers on the event and its subject
action = "resume-origin"                  # resume the run or headless session that asked
enabled = true

[[triggers]]
name = "verify-on-delivery"
on = "task.transitioned"
when = { to = "delivered" }
action = "start-run"
run = { mode = "verify", tool = "cross_agent_order" }   # the first independent tool
enabled = false                            # launching agents is always opt-in
```

**Actions:**

| Action | Effect |
| --- | --- |
| `notify` | Records the event for its session(s) and the UI. Always safe. |
| `resume-origin` | Continues the run or headless session recorded as the origin. |
| `start-run` | Launches a run with the given parameters, through the normal preview and guards; the plan hash is computed by the engine. |
| `command` | Runs a fixed `ai-orch` subcommand. Arbitrary shell is not allowed. |

**The trigger engine** is `ai-orch triggers run-once` (it processes new events since its own cursor) and `ai-orch triggers daemon`. The daemon is started by the UI backend when the backend is running, and is otherwise optional.

**Safety:**

- every rule that launches an agent defaults to `enabled = false`;
- a global kill switch: `[triggers] enabled = false`, and a UI toggle;
- events are deduplicated by `id`;
- each rule has a rate limit (`max_per_hour`, default 6) and a loop guard (an event caused by a trigger-launched run carries `cause`, and a rule never fires on its own descendants beyond depth 3);
- every firing is recorded as an event `trigger.fired`, with the rule and the result.

## 6. UI

- A notification area (bell) listing recent events relevant to the owner.
- A Triggers page: the rules with on/off toggles (the rule definitions stay in config; toggling edits config through preview → confirm), the last firings, and the kill switch.
- The Decisions tab gains the "Answered, awaiting application" group (§3).
- Session chips: which orchestration sessions are registered, last seen, pending event count.

## 7. Out of scope

- Delivering events to remote machines or to other users.
- Arbitrary shell actions in triggers.
