# Peer messaging between workspace orchestrators

- status: **superseded** (2026-10-18) by `orchestration-broker-mcp.md`; kept for history (draft 1, reviewed by Codex)
- owner request (2026-10-18): "a communication mechanism between the orchestrator of this workspace and the orchestrators of other workspaces, taken from the workspace configuration; if possible across tools too (Claude with Kilo, etc.)"
- builds on: `events-and-triggers.md` (§1 event store, §2 session registry, §4 delivery per tool, §0 headless orchestrator, §0c E3 proposals), `orchestration-config-and-agents-md.md` (config layering)

## 0. Problem

Today a session in one workspace reaches a session in another through Claude Code's `SendMessage`. That works only
between Claude sessions, and the address is the session name (e.g. `d4science-evolution-assurance-53`), which changes
at every restart: the receiving workspace has to publish its current name by hand (`WORKSPACES.md`). A message sent
while the target is not running is lost, there is no thread, no record in either workspace, no policy (a blind
re-run workspace must receive nothing), and Kilo or Codex orchestrators cannot take part.

## 1. Principles

1. **The address is the workspace, not the session.** A stable workspace id from configuration; sessions come and go.
2. **The record is durable and tool-neutral.** A message is a file in the target workspace, written and read through
   `ai-orch`, so Claude, Kilo, Codex, headless runs and the UI all use the same path. Live channels (SendMessage, a
   watcher, a toast) are **nudges** that point at the record, never the record itself.
3. **The recipient is the target's orchestrator role**, which is headless and never blocked by interactive sessions
   (`events-and-triggers.md` §0a). Interactive sessions are consoles: they can send and read mail, but they are not
   the address.
4. **A peer message is untrusted input.** It never mutates the target directly: it becomes something the target's
   orchestrator reads (a turn with reduced capability, like `event_batch`), and any action it suggests goes through the
   target's normal gates (questions, proposals with owner confirmation).
5. **Policy is declared by the receiving and the sending workspace.** Isolation ("blind") is enforced by the engine on
   both ends, not left to the agent's judgment.

## 2. Workspace identity and directory

- **Id:** `[workspace] id = "<slug>"` in the project config (`orchestration.toml` or `.ai-orchestration.local.toml`).
  Slug: `^[a-z0-9][a-z0-9-]{1,47}$`. Default when absent: the folder name, slugified; `ai-orch peers whoami` prints it
  with its source (`config` | `derived`). Optional `[workspace] title` (human label).
- **Directory (local, per user):** `~/.config/ai-orchestration/workspaces.toml`, one entry per workspace:
  `[[workspace]] id, path, title, tools (orchestrator tool), registered_at`. Written only by `ai-orch peers register`
  (preview, hash, apply; under a lock), which `ai-orch setup` also offers. An entry whose path no longer exists is
  reported as stale by `peers list` and the Doctor, never deleted silently.
- **Resolution:** `peers send --to <id>` resolves the id through the directory; a path is also accepted
  (`--to-path DIR`) and must contain a workspace whose id matches, so a renamed folder does not receive mail meant for
  another workspace.

## 3. Messages and the mailbox

- **Store:** `<target>/.ai-orchestration/mailbox/inbox/<msg_id>.json`; the sender keeps a copy in
  `<sender>/.ai-orchestration/mailbox/outbox/<msg_id>.json`. Both are git-excluded (like the rest of `.ai-orchestration/`).
- **Write path:** the sender writes a temp file in the target's `mailbox/incoming/` and renames it into `inbox/`
  (atomic on the same filesystem), then appends `peer.message_received` to the **target's** event store through the
  target's own `orchestration_events` code path (lock + counter), and `peer.message_sent` to its own.
  If the target's event store cannot be locked within a timeout, the file stays in `inbox/` and the target's
  `peers inbox` (or the Doctor, or `events reconcile`) emits the missing event later: the file is the truth.
- **Message fields:** `msg_id` (ULID), `from` (`workspace_id`, `path`, `tool`, `session_id` or `-`, `actor`:
  `orchestrator` | `owner` | `run:<id>`), `to` (`workspace_id`), `kind` (`info` | `request` | `question` | `reply` |
  `handoff`), `subject` (≤ 120 chars), `body` (Markdown, ≤ 32 KiB), `refs` (paths or ids in the **sender's** workspace,
  never file contents), `thread` (`msg_id` of the first message), `in_reply_to`, `created_at`, `expires_at` (optional),
  `body_sha256`.
- **State (receiver side, in the same file under `receipt`):** `received` → `read` (`by`, `at`) → `answered`
  (`reply_msg_id`) | `declined` (`reason`) | `expired`. Only the receiver's `ai-orch` changes it; the sender learns the
  outcome from the reply message (no cross-workspace writes other than the delivery itself).
- **No attachments in v1.** Large content is referenced by path; the receiver decides whether to read it.

## 4. Commands

- `ai-orch peers whoami | list [--json]`
- `ai-orch peers register [--id ID] [--title T] [--dry-run | --expect-hash H]`
- `ai-orch peers send --to ID --kind K --subject S (--body TEXT | --body-file F) [--ref R]... [--thread T] [--in-reply-to M] [--dry-run] --json`
  (the dry run prints the resolved target, the policy decision and the exact record)
- `ai-orch peers inbox [--unread] [--thread T] --json`, `peers show MSG_ID`, `peers read MSG_ID`
- `ai-orch peers reply MSG_ID (--body … | --body-file …)`, `peers decline MSG_ID --reason R`
- `ai-orch peers outbox [--json]` (with the replies matched to each sent message)
- `ai-orch peers watch [--timeout S]`: blocks until an unread message arrives, then prints it and exits (for
  background watchers of interactive sessions, §5).

## 5. Delivery: the recipient is the target's headless orchestrator

The record is always the mailbox file plus the `peer.message_received` event. Per `events-and-triggers.md` §0a the
recipient is the **orchestrator role** of the target workspace, which is headless and drained by its `serve` worker:

- A built-in trigger rule on `peer.message_received` enqueues a `peer_message` turn (`policy = reduced_capability`, the
  body wrapped as `untrusted_peer_data` with provenance `peer:<from.workspace_id>:<msg_id>`). The turn can read, reply,
  decline, file a question for the owner, or create a proposal; it cannot run mutating commands directly.
- **Target without a working orchestrator:** the message is still delivered (the file is the record). `peers send`
  reports `target_orchestrator: missing | stopped | running` in its result, so the sender knows the reply may wait. The
  next `orchestrator ensure` in the target picks the mail up from the event backlog.
- **Interactive consoles** (any tool) are only told, never relied upon: the VS Code toast and the UI badge from the event
  (12.7 watcher), and the skills' instruction to mention unread peer mail when the owner opens a session. A live Claude
  console may also get a one-line `SendMessage` nudge from a Claude sender when the target's session registry lists its
  `sendmessage_name`; this is optional and carries no content.

Session registry addition: `sendmessage_name` (optional) for interactive Claude consoles, set at registration from the
session's own name, so nudges no longer depend on a hand-kept `WORKSPACES.md`.

## 6. Policy

Declared in each workspace's config:

```toml
[peers]
isolation = "open"            # open | restricted | blind
accept_from = ["*"]           # workspace ids or "*"; used when isolation = "restricted"
send_to = ["*"]               # same, for outgoing mail
deny = []                     # always refused, both directions
max_body_kib = 32
auto_turn = true              # enqueue a peer_message turn for the headless orchestrator
```

- `blind`: the workspace neither sends nor receives; `peers send` **to** a blind workspace is refused by the sender's
  engine after reading the target's config (the refusal names the reason, without content). A blind workspace's own
  `peers` commands refuse to send.
- Both sides are checked: the sender's `send_to`/`deny` and the target's `isolation`/`accept_from`/`deny`. The decision
  is part of the dry run.
- Content rules (all workspaces): no secrets, hosts or finding details in bodies; the skills say so and `peers send`
  runs a cheap secret scan (the same patterns as the Doctor's) that blocks obvious tokens and keys.

## 7. Cross-tool

Because the record and the commands are `ai-orch`, any orchestrator can talk to any other: a Claude orchestrator in one
workspace and a Kilo headless orchestrator in another exchange mail the same way. The tool only changes how the
receiver is nudged (§5). No tool-specific transport is required; SendMessage stays an optional accelerator between
live Claude sessions.

## 8. UI and VS Code

- Inbox gets a "Peer mail" view: threads, unread badge, reply/decline (preview → apply), the policy decision on
  failed sends, and the directory (`peers list`) with stale entries flagged.
- VS Code: the same view through the bridge; toast on `peer.message_received`.

## 9. Out of scope (v1)

Remote machines and network transport; encryption and signatures (same user, same machine); attachments; group
messages (one recipient per message; a list can loop over `send`).

## 10. Open questions for the owner

- Q-a: Should the directory be global per user (`~/.config/ai-orchestration/workspaces.toml`, proposed) or should each
  workspace declare its peers in its own config only?
- Q-b: Should the headless orchestrator answer `request` messages on its own (reduced capability), or always ask the
  owner first?
- Decided (owner, 2026-10-18): the recipient is the headless role; any session ensures it exists (`orchestrator ensure`,
  `events-and-triggers.md` §0a).
