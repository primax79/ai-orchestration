# Spec: Events, orchestration sessions and triggers

- **Status:** draft for review (2026-10-17)
- **Drives:** initiative [12](../12-events-and-triggers/plan.md)
- **Origin:** owner request (2026-10-17). Interactions in the UI (answering a question, marking a note ready, a run finishing) change files, but nothing reacts to them until an orchestrator happens to look. The system needs explicit events and a reference to the orchestration session that must react.
- **Supersedes:** spec 08 §5 "Answer and resume run" (task 08.6 becomes a trigger rule here). It also closes the gap "answered but not yet applied".

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
