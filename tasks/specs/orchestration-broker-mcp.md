# Orchestration broker: one MCP server per user, many workspaces, many projects

- status: draft 2 (2026-10-18). Supersedes `peer-messaging.md` (draft 1, kept for history). To be reviewed by Gemini
  (kilo-mcp) and Codex before the plan is written.
- owner requests (2026-10-18):
  - a way for the orchestrator of one workspace to talk to the orchestrators of other workspaces, taken from the
    workspace configuration, across tools (Claude with Kilo, …);
  - from another workspace one usually talks to the orchestrator, but sometimes to an interactive session;
  - the orchestrator stays headless, is never blocked by interactive conversations, and any session brings it to life
    when it is missing (`events-and-triggers.md` §0a);
  - the `ai-orchestration` backend becomes an MCP server, and task updates, formalisation and similar work are
    delegated to it (and to the orchestrator behind it) instead of to skills;
  - it is multi-workspace, and a workspace can contain several projects, each with its own tasks.
- inputs: Codex review of draft 1 (2026-10-18, 12 items), Gemini review (pending).

## 1. Model

```
user (one broker process)
└── workspace            a registered folder; owns ONE orchestrator role; the unit of addressing for mail
    └── project          a task tree (a folder with tasks/00-INDEX.md); one or more per workspace
        └── task / question / note / use case   (ids unique only inside their project)
```

- **Workspace:** registered root folder with a stable identity (§2). It owns one headless orchestrator role (§5), one
  event store and one mailbox. Example: `~/works/ai-coding-tools`.
- **Project:** a task tree inside the workspace. Discovered (any `tasks/00-INDEX.md` under the root, not inside a
  `.kilo/worktrees/`, `node_modules/`, `references/` or another registered workspace) and confirmable in the workspace
  config (`[[workspace.projects]] id, path`). The workspace's own top-level `tasks/` is the project `_workspace`.
  Example: `ai-coding-tools` has `_workspace` (its registry), `ai-orchestration`, `claude-mcp`, …
- **Nesting rule:** a project belongs to exactly one workspace, the nearest registered ancestor. A folder registered as
  a workspace inside another workspace is excluded from the outer one (no double ownership of the same task tree).
- **Qualified ids:** `workspace:project/ID`, e.g. `ai-coding-tools:ai-orchestration/T025`,
  `ai-coding-tools:_workspace/T014`. Inside a project the bare id stays valid; across projects or workspaces the
  qualified form is mandatory. Citations in chat follow the short-title rule: `ai-orchestration/T025 (short title field)`.
- **Cross-project dependencies:** `depends-on` accepts qualified ids; the graph resolves them through the broker
  (read-only; a dependency on another workspace is shown, never transitioned from here).

## 2. Identity and registry

- Each workspace carries an immutable id in its config: `[workspace] uuid = "<UUIDv4>"` plus a human slug
  `[workspace] id = "ai-coding-tools"` (`^[a-z0-9][a-z0-9-]{1,47}$`). The uuid is what the broker keys on (Codex 10:
  folder names collide and renames break lookups); the slug is the address people type.
- Registry: owned by the broker, stored at `~/.config/ai-orchestration/broker/registry.sqlite` (or JSON under a lock;
  the choice is part of the plan), with uuid → slug, canonical path, device/inode, projects, last_seen.
- Registration: `workspace.register` (preview → apply), offered by `orchestrator ensure` and by the setup wizard.
  Before every write into a workspace the broker re-verifies canonical path, device/inode and uuid, and refuses
  symlinked `.ai-orchestration` components (Codex 10). Stale entries are reported, never deleted silently.

## 3. The broker

- **One process per user**, `ai-orch broker serve`, the evolution of the current UI backend (`ai-orchestration-ui`):
  - **MCP server** (streamable HTTP on localhost, token as today), plus a thin **stdio shim** (`ai-orch mcp`) for
    clients that only speak stdio; the shim starts the broker if it is not running and forwards to it.
  - **Web UI and VS Code bridge** keep working on the same process (the UI gains a workspace/project switcher).
  - **Runs the orchestrator workers** of the registered workspaces (§5), so there is no worker per workspace and no
    second trigger daemon: trigger evaluation lives in the broker (resolves Codex 6).
  - **Single writer** for the shared stores (registry, mailboxes, events, queues): every mutation goes through the
    broker, under its locks, so cross-workspace delivery is a local transaction instead of one process writing into
    another workspace's files (resolves Codex 3, 4, 11).
- The CLI (`ai-orch …`) stays and keeps working without the broker for single-project use (offline, CI); when the
  broker is running, the CLI's mutating commands go through it (so locks are not bypassed).
- Start: by `orchestrator ensure`, by the stdio shim, by the UI launcher, or at login (optional launchd/systemd unit,
  owner's choice).

## 4. MCP surface

Tools (all scoped by `workspace` and `project`; defaults from the caller's cwd, resolved by the broker):

- **Read:** `tasks.list`, `tasks.show`, `tasks.graph`, `tasks.next`, `questions.list`, `inbox.list`, `runs.list`,
  `events.tail`, `workspaces.list`, `projects.list`, `orchestrator.status`, `whoami`.
- **Deterministic writes** (preview → apply with the hash in one round trip: the tool returns the plan and a
  `confirm_token`; a second call with the token applies it): `tasks.new`, `tasks.transition`, `tasks.set_*`
  (priority, size, deps, kind, labels, short), `tasks.child_add`, `questions.ask|answer|apply`, `inbox.add_note`,
  `inbox.attach`. The broker enforces the task format; skills no longer explain file formats.
- **Delegation to the orchestrator:** `orchestrator.ask(workspace, text, kind)` with `kind` in `formalize` (turn a
  request into tasks/spec), `update` (bring task state in line with what happened), `plan`, `review`, `free`. It
  enqueues a turn and returns a `ticket`; `orchestrator.ticket(ticket)` returns state and the reply when done. This is
  how sessions "delegate task updates and formalisation" instead of doing them with skills. The orchestrator is the
  only writer of task content that needs judgment; deterministic fields can still be set by anyone through the tools.
- **Mail:** `mail.send(to, kind, subject, body, refs?, thread?, in_reply_to?)`, `mail.inbox`, `mail.read`,
  `mail.reply`, `mail.decline`. Addresses:
  - `workspace` (slug or uuid) → that workspace's orchestrator role (the normal case);
  - `workspace/session-name` → a live interactive console of that workspace (§6);
  - `workspace:project` is not a mail address (projects have no inbox; the orchestrator routes).
- **Lifecycle:** `orchestrator.ensure(workspace, dry_run)`, `orchestrator.pause|resume`, `console.register` (§6).
- Resources: the project index and the specs as MCP resources, so clients can read them without file access.

## 5. Orchestrator per workspace

- Unchanged from `events-and-triggers.md` §0/§0a except: the worker loop runs inside the broker, one logical worker
  per workspace, serialised per workspace, parallel across workspaces.
- The orchestrator works on **all projects of its workspace**; a turn names the project(s) it touched. Its tool calls
  to task data go through the same MCP surface (it is a client of the broker too), so its writes are validated like
  everyone else's.
- Fixes required by the Codex review, kept here because they are about the orchestrator: triggers enqueue through the
  canonical queue under the lock and the delivery cursor advances only after a turn completes (`server-and-bindings`
  T026); `status` is read-only (no auto-registration); explicit stop/pause is respected by `ensure` unless the owner
  asks to resume; an interrupted mutating turn is marked `outcome_unknown` for the owner instead of being retried
  (Codex 8, 9).

## 6. Consoles: interactive sessions

- Any interactive session (Claude, Kilo, Codex) connected to the broker calls `console.register(name, tool)` at start
  (the skills say so; for Claude the name is its SendMessage name). It is a console of the workspace of its cwd.
- Mail to `workspace/session-name` is stored for that console. The console learns about it pull-style: every broker
  tool result carries `unread_mail: N` in a small envelope field, and the skills tell the session to look when N > 0.
  Optional nudges: a watcher (`ai-orch mail watch`) for Claude, the VS Code toast, the UI badge.
- A console that disconnects keeps its mailbox for a retention period; mail to a console that no longer exists is
  returned to the sender with `console_gone` (and can be re-sent to the workspace orchestrator).

## 7. Mail safety

- **Quarantine (Codex 1):** mail addressed to an orchestrator never enters the persistent orchestrator session as raw
  text. A fresh, stateless, no-tools classifier turn (cheap model) reads it and produces a structured result
  (`summary`, `intent`, `requested_actions[]`, `questions[]`, `suspicious: bool`). Only that structured result reaches
  the orchestrator, marked `untrusted_peer_data` with provenance. Reading referenced files or sending a substantive
  reply that quotes workspace content needs the owner's approval (a proposal, §0c E3).
- **Structured effects (Codex 5):** the orchestrator acts on mail through broker tools (reply, decline, create a
  question, create a proposal), never through shell commands; the broker applies them.
- **Policy** per workspace config: `[mail] isolation = open | restricted | blind`, `accept_from`, `send_to`, `deny`,
  `max_body_kib`. The broker checks both sides inside one transaction, at send time and again before the
  classifier turn, and quarantines (does not process) mail whose policy changed meanwhile (Codex 11). An unregistered
  or unconfigured target is `deny` by default.
- **Content:** bodies are Markdown ≤ 32 KiB, references are ids or paths in the sender's workspace, no attachments in v1.
  Secret scanning is best-effort and documented as such (Codex 12).

## 8. What the skills become

- `task-pipeline`, `orchestration-workflow` and the bindings shrink to: how to reach the broker (MCP tools), the
  citation rule, when to `orchestrator.ask` (formalize, update) versus calling a deterministic tool, and how to read
  `unread_mail`. Format rules, transitions and index sync move into the broker and stop depending on the agent having
  read the skill.
- The CLI-based instructions stay as a fallback for environments without the broker.

## 9. Migration

1. Fix the queue/cursor race (T026) and make `status` read-only: independent of the broker.
2. Registry + identity (uuid, projects discovery, qualified ids in the engine).
3. Broker process from the UI backend: MCP read tools, then deterministic writes with confirm tokens.
4. Orchestrator workers in the broker + `orchestrator.ask` tickets.
5. Mail (workspace orchestrator first, then consoles), quarantine classifier, policy.
6. Skills rewritten to use the broker; the CLI path stays as fallback.
7. UI: workspace/project switcher, mail view, consoles.

## 10. Open questions for the owner

- Q-a: Start the broker at login (launchd unit) or only on demand (first `ai-orch`/MCP use)?
- Q-b: Projects inside a workspace: confirmed explicitly in the workspace config, or discovered automatically with the
  exclusions above?
- Q-c: Should a project be allowed to be its own workspace as well (for example `ai-orchestration` opened alone), with
  the nesting rule deciding ownership, or must a folder be either a workspace or a project?
- Q-d: The orchestrator's model for the mail classifier: the cheapest model of the workspace's orchestrator tool, or a
  fixed one?

## 11. Out of scope (v1)

Other machines and network transport; signatures and encryption; attachments in mail; group messages; editing task
trees of another workspace (read-only cross-workspace).
