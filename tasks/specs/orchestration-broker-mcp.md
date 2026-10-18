# Orchestration broker: one MCP server per user, many workspaces, many projects

- status: draft 4 (2026-10-18): v1 scope after two review rounds. Supersedes `peer-messaging.md`.
- owner requests (2026-10-18):
  - the orchestrator of one workspace talks to the orchestrators of other workspaces, across tools (Claude, Kilo, Codex);
  - from another workspace one usually talks to the orchestrator, sometimes to an interactive session;
  - the orchestrator is headless, never blocked by interactive conversations, and any session brings it to life when it
    is missing (`events-and-triggers.md` §0a);
  - the `ai-orchestration` backend becomes an MCP server; task updates and formalisation are delegated to it and to the
    orchestrator behind it instead of to skills;
  - multi-workspace, and a workspace can contain several projects with their own tasks.
- reviews: round 1 on draft 1 (`../_reviews/2026-10-18-peer-messaging-review-{codex,gemini}.md`, C1–C12, G1–G12),
  round 2 on draft 3 (`../_reviews/2026-10-18-broker-mcp-review-{codex,gemini}.md`, referenced as C2-n and G2-n).
  Draft 4 adopts Codex's "simpler v1" and the converging items of both reviewers.

## 1. Model

```text
user (one broker process)
└── workspace     registered folder; one headless orchestrator role; the mail address
    └── project   a task tree (folder with tasks/00-INDEX.md), declared in the workspace config
        └── task / question / note / use case   (ids unique only inside their project)
```

- **Workspace:** registered root folder, immutable `uuid` + human `slug` in its config (`[workspace] uuid, id`). It owns
  one orchestrator role, one event store, one mailbox.
- **Project (v1: explicit, C2-6, G2-8):** `[[workspace.projects]] uuid, id, path` in the workspace config. The
  workspace's top-level `tasks/` is the project `_workspace`. `ai-orch projects discover` only **proposes** entries
  (it skips hidden folders, git-ignored paths, build/dependency/scratch/fixture folders, worktrees and other registered
  workspaces); nothing is picked up silently.
- **Nesting (owner decision Q-c, 2026-10-18):** a folder may be registered as a workspace even inside another
  workspace; the **nearest registered workspace owns** every task tree under it. The outer workspace then lists the
  inner one as a *sub-workspace* (read-only view, mail goes to the inner orchestrator), never as its own project, so
  one task tree always has exactly one orchestrator. Registering an inner workspace moves ownership of its projects
  out of the outer one, shown in the registration preview; unregistering gives them back.
- **Placement rule (owner, 2026-10-18):** a project's tasks live in the project. The workspace tree (`_workspace`) holds
  only **coordination** tasks: work that spans several projects (a cross-repo initiative, a coordinated release, a
  decision affecting more than one project). A coordination task names what it coordinates with
  `coordinates: project/ID, …`; its progress view is derived from those tasks (read-only), and it does not duplicate
  their content. `validate` warns when a workspace task coordinates nothing or touches a single project's paths
  ("move it to the project"); `ai-orch tasks move ID --to-project P` relocates a task with a preview, rewriting its id
  in the target tree and leaving a pointer behind.
- **Qualified references (C2-5, G2-3):** one grammar, `QualifiedTaskRef = [workspace ":"] [project "/"] ID`, with a
  single parser/canonicaliser in the engine. Malformed prefixes are errors, never prose. **v1 scope:** the broker and
  chat use qualified refs for addressing and citation (`ai-coding-tools:ai-orchestration/T025 (short title field)`);
  on-disk `depends-on` stays project-local (bare ids). The one cross-tree link in v1 is `coordinates:` from the
  workspace tree to its own projects (`project/ID`, resolved read-only by the broker and by the CLI). General
  cross-project `depends-on` and cross-workspace links are v2.

## 2. The broker process

- `ai-orch broker serve`: one per user, the evolution of the current UI backend. Single instance guarded by
  `broker.lock` (`flock LOCK_EX|LOCK_NB`) in the global config dir, readiness written to `broker.json` (pid, port,
  started_at) after the lock is held (G2-2, G2-4).
- **Transports:** MCP over streamable HTTP on localhost (token as today) and an **stdio shim** `ai-orch mcp`
  (Codex only speaks stdio, G2-4). The shim answers `initialize` immediately from static capabilities, takes
  `broker.launch.lock` before starting a broker (one launcher, others poll readiness), then forwards. `ai-orch mcp
  --local` serves the same tools in-process for one workspace (tests, CI, broker unavailable) and takes the same
  on-disk locks.
- **Locks are on disk and shared with the CLI (C2-2, G2-2):** every task mutation, from the broker or the CLI, takes
  the project's existing `tasks/.ai-orch.lock` (`task_write_lock`) and checks file hashes (CAS). The CLI never decides
  "broker down" from an HTTP timeout: if `broker.lock` is held it routes mutating commands through the broker (or
  fails with "busy"); if not, it writes directly under the same project lock. No split brain.
- **Store:** registry, mailboxes, tickets and job states in SQLite (WAL) under the global config dir; task trees stay
  Markdown in the projects.
- **Recovery (C2-1, G2-1):**
  - child agent processes (orchestrator turns) run detached (`start_new_session`), with pid, start time, session id and
    log path persisted before the turn is marked running;
  - on start, the broker reconciles: a live child is **re-attached** (log tailing resumes), a dead one with a complete
    transcript is finalised, an interrupted mutating one becomes `outcome_unknown` for the owner;
  - every mutating MCP call carries an idempotency key; the broker stores its terminal result, so a client that lost
    the response gets the same result on retry;
  - `ai-orch broker stop --drain T` stops claiming work and waits for running turns.
- Start: on demand by the shim, the CLI or the UI (owner decision Q-a); no login service. While nothing is open,
  orchestrators do not run and mail waits.

## 3. MCP surface (v1)

Workspace and project are **explicit arguments or bound at console registration**, never inferred from the broker's
cwd (C2-4). `whoami` reports the binding.

- **Read:** `whoami`, `workspaces.list`, `projects.list`, `tasks.list|show|graph|next`, `questions.list`,
  `inbox.list`, `runs.list`, `events.tail`, `orchestrator.status`, `mail.inbox`.
- **Deterministic writes (C2-3 vs G2-5, converged):** applied directly, with optimistic concurrency: the caller may pass
  `expect_hash` (from its last read); the result returns the new hash. `preview: true` returns the plan without
  writing. Two-step `confirm_token` exists only for destructive or owner-facing actions (drop, bulk rollback, global
  config): single-use, short expiry, bound to the caller, tool, canonical arguments, uuids and observed file hashes,
  with a stored terminal receipt for replays. Tools: `tasks.new|transition|set_*|child_add`,
  `questions.ask|answer|apply`, `inbox.add_note|attach`. The broker enforces the task format.
- **Delegation:** `orchestrator.ask(workspace, kind, text)` with `kind` in `formalize | update | plan | review | free`
  enqueues a turn and returns a durable `ticket`; `orchestrator.ticket(id)` returns state and reply. This is how
  sessions delegate task bookkeeping and formalisation; the orchestrator writes through the same tools.
- **Mail:** `mail.send|inbox|read|reply|decline`, `mail.poll` (explicit, cheap). Addresses: `workspace` → its
  orchestrator; `workspace/console` → a registered console (§5).
- **Lifecycle:** `orchestrator.ensure(workspace, dry_run)` (config writes under `config_lock` with the base hash
  re-read under the lock, C7), `orchestrator.pause|resume`, `console.register`.

### 3a. Findings of the client spike (16.1, 2026-10-18; normative)

All three clients work through the stdio shim (`16-orchestration-broker/notes/16.1-client-spike.md`), with these rules:

- Results are serialised **without null fields**: Claude Code silently drops a server whose tool list carries
  `"title": null` and similar.
- Read tools are **compact and paged** with a response cap (≈1 MB results failed in the relay, and are useless in a
  model's context): `tasks.list` returns id, short title, state, priority and project; details come from `tasks.show`.
- The MCP registration written by the Doctor/setup sets Codex's per-server `default_tools_approval_mode` (without it,
  unattended `codex exec` cancels every MCP call); Kilo uses `"mcp": {"<name>": {"type": "local", "command": [...],
  "environment": {...}}}`.
- Tool and field names are part of the contract and are fixed in this spec before 16.5.

### 3b. Tool contract v1 (names and fields are normative; 16.5 implements exactly this)

Conventions: tool names are `snake_case` with a dotted group (`tasks.list`); every tool takes `workspace` (slug or
uuid) and, where it acts on a tree, `project` (slug); ids inside a project are bare. Every result is a JSON object in
one text content item, with `ok: bool`; errors carry `error` (stable kebab-case code) and `message`. No nulls: absent
means unknown. Lists are paged: `cursor` in, `next_cursor` out, `limit` default 50, max 200; responses capped at 256 KiB
(a truncated list says so and returns `next_cursor`). Mutations accept `idempotency_key` and `expect_hash`, and return
the new `hash`.

| Tool | Arguments | Result (besides `ok`) |
| --- | --- | --- |
| `whoami` | – | `broker: {pid, version, started_at}`, `console: {uuid, name, workspace, project}`, `unread_mail` |
| `workspaces.list` | `cursor?, limit?` | `items: [{uuid, slug, title, path, orchestrator: missing\|stopped\|running\|paused, unread_mail}]` |
| `projects.list` | `workspace` | `items: [{uuid, slug, path, kind: project\|_workspace\|sub_workspace}]` |
| `tasks.list` | `workspace, project, state?[], kind?, label?, text?, cursor?, limit?` | `items: [{id, short_title, title, state, priority, kind, size?, parent?, depends_on: [], hash}]` |
| `tasks.show` | `workspace, project, id` | `task: {id, short_title, title, state, header: {…}, goal, steps, verification, children: [], attachments: [], hash, path}` |
| `tasks.next` | `workspace, project?` | `items` as `tasks.list`, ready queue order |
| `tasks.graph` | `workspace, project` | `nodes: [{id, short_title, state, column}]`, `edges: [[from, to]]`, `ready: []` (no Mermaid) |
| `tasks.new` | `workspace, project, title, short, goal, category?, priority?, priority_reason?, kind?, parent?` | `id, hash, path` |
| `tasks.transition` | `workspace, project, id, to, note?` | `id, from, to, hash` |
| `tasks.set` | `workspace, project, id, field: priority\|size\|deps\|kind\|labels\|short, value` | `id, field, value, hash` |
| `questions.list` | `workspace, project?, status?` | `items: [{id, short_title, question, status, blocks: [], decider}]` |
| `questions.ask` | `workspace, project, question, short, context, options: [{label, consequences}], recommended?, blocks?: []` | `id, hash` |
| `questions.answer` | `workspace, project, id, choice, text?` | `id, unblocked: []` |
| `inbox.add_note` | `workspace, project, title, body, kind?` | `id, path` |
| `orchestrator.status` | `workspace` | `state, tool, model, generation, queue_length, worker: {alive, heartbeat_at}, unread_mail` |
| `orchestrator.ensure` | `workspace, dry_run?` | `plan: [{step, action}]`, `applied: bool` |
| `orchestrator.ask` | `workspace, kind: formalize\|update\|plan\|review\|free, text, project?` | `ticket` |
| `orchestrator.ticket` | `ticket` | `state: queued\|running\|done\|failed\|outcome_unknown, reply?, turn_id?` |
| `mail.send` | `to, kind: info\|request\|question\|reply\|handoff, subject, body, refs?: [], thread?, in_reply_to?` | `msg_id, delivered_to: workspace\|console, target_orchestrator` |
| `mail.inbox` | `workspace?, unread_only?, cursor?, limit?` | `items: [{msg_id, from, kind, subject, received_at, state, size}]` (no bodies) |
| `mail.read` | `msg_id` | `message: {…, body}` (refused for orchestrator mail not yet accepted by the owner) |
| `mail.reply` / `mail.decline` | `msg_id, body` / `msg_id, reason` | `msg_id` |
| `mail.poll` | – | `unread_mail, newest: [{msg_id, from, subject}]` |
| `console.register` | `name` | `console: {uuid, name}` |

Destructive or owner-facing actions (`tasks.drop`, bulk rollback, global config writes, `mail.accept`) are not MCP
tools in v1: they stay in the UI/CLI with `confirm_token`.

## 4. Orchestrator per workspace

- `events-and-triggers.md` §0/§0a, with the worker loop inside the broker: serialised per workspace, parallel across
  workspaces; trigger evaluation in the broker (holds the old daemon lock; `triggers daemon` superseded).
- Required fixes, tracked separately: T026 (trigger enqueue race, separate cursors, read-only status), T027 (no
  recovery of a claim within its lease/startup grace), T028 (reduced capability enforced on every tool including Kilo;
  per-turn nonce delimiters).
- Liveness in `orchestrator/worker.json` from a heartbeat thread; staleness checks the process table.

## 5. Consoles

- A console is an interactive session (any tool) known to the broker. **Registration is lazy (G2-7):** the first MCP
  call of a client creates a console bound to the workspace/project the client names (or the one in its MCP server
  config), with a broker-issued `console_uuid` and secret and a lease renewed by every call (C2-7). `console.register`
  only sets a human name (for Claude, its SendMessage name) and must be unique in the workspace.
- Mail to `workspace/console-name` lands in the console's mailbox, which survives reconnects for a retention period.
  Consoles learn about it pull-style: `mail.poll`, `whoami` and `orchestrator.status` report `unread_mail`; when it is
  > 0 the broker appends a one-line human-readable notice to the text content of tool results (G2-6), never a
  non-standard field. Watchers, toasts and SendMessage nudges are optional adapters.
- Mail to a console that is gone is returned with `console_gone`; the sender may re-send it to the workspace.

## 6. Mail safety (v1)

- **No automatic classifier in v1 (C2-8, G2-9).** An unattended orchestrator receives only **safe metadata** of new mail
  (from, kind, subject, size, policy decision), never the raw body. The body is read by the orchestrator only after the
  owner accepts the message (Decisions/Inbox, or `mail.accept` by the owner), and then wrapped with a per-turn nonce.
  A console reads its own mail directly (it is a human-attended session).
- **Effects are structured (C5):** the orchestrator acts on mail only through broker tools (reply, decline, question,
  proposal); mail never causes shell commands.
- **Policy:** `[mail] isolation = open | restricted | blind`, `accept_from`, `send_to`, `deny`, `max_body_kib` (32),
  `max_received_per_hour` (20). Checked for both sides in one broker transaction, at send and again at acceptance;
  unregistered or unconfigured targets are denied; blind workspaces neither send nor receive.
- **Outcomes reach the sender:** decline and expiry send an automatic reply; events `mail.received|read|answered|
  declined|expired`.
- **References:** ids or root-relative paths in the sender's workspace, validated; read only through `mail.fetch_ref`
  after acceptance and policy/size checks.
- **Secrets:** best-effort scan with named patterns (AWS, GitHub, provider keys, private-key blocks), tested; it blocks
  or warns and never claims more.

## 7. What the skills become

`task-pipeline`, `orchestration-workflow` and the bindings shrink to: reach the broker (MCP), cite `ID (short title)`
(qualified across projects), delegate formalisation and state updates with `orchestrator.ask`, use deterministic tools
for simple fields, and check `unread_mail`. Format rules and transitions live in the broker. CLI instructions stay as
the fallback.

## 7b. Interface: project view and workspace view (owner, 2026-10-18)

The UI (web and VS Code) follows the placement rule:

- **Project view:** one project's tree, exactly as today (backlog, Kanban, tree, timeline, decisions, inbox, runs),
  with bare ids. A project selector switches between the projects of the workspace.
- **Workspace view (common):** all projects of the workspace together, plus the coordination tasks of `_workspace`.
  Every item shows its qualified id and project (`ai-orchestration/T025`), filters and grouping by project, and a
  coordination task expands into the project tasks it `coordinates`, with their live states. Questions, inbox, runs
  and mail are workspace-wide lists with a project column. Writes from this view always target the item's own project.
- The selected view and project are remembered per window; deep links carry `workspace:project/ID`.
- A third level, **all workspaces** (read-only overview: orchestrator status, unread mail, open questions per
  workspace), comes with the broker's registry.

## 8. Migration (v1), each step independently shippable (C2-9)

1. **Invariants first:** T026, T027, T028; `status` read-only; config CAS under `config_lock` (C7).
2. **MCP client spike (gate):** a minimal broker + stdio shim with two read tools, exercised from Claude Code, Kilo and
   Codex: simultaneous shim starts, broker down/up, reconnect, long tickets, text-content notices. The plan continues
   only if all three work; otherwise the spec is amended.
3. Shared on-disk locking and idempotency keys in the engine; broker singleton and readiness.
4. Registry: workspace uuid/slug, explicit projects, `projects discover` (proposals only), `QualifiedTaskRef` parser,
   `coordinates:` links and the placement rule (`validate` warning, `tasks move --to-project`).
5. Read-only broker tools; then deterministic writes (CAS, idempotency, confirm tokens for destructive actions).
6. Skills switched incrementally to the broker, CLI fallback kept.
7. Orchestrator workers inside the broker, recovery/re-attachment, `orchestrator.ask` tickets.
8. Mail to workspace orchestrators (metadata-only quarantine, policy, limits); then consoles; UI mail view.
9. Interface: project view and common workspace view (§7b), then the all-workspaces overview.

**v2 (not now):** cross-project `depends-on` and graphs, automatic classifier turns, reactive notifications,
attachments, other machines.

## 9. Open questions for the owner

- Q-a: decided (2026-10-18): on demand (first shim/CLI/UI use); no login service.
- Q-c: decided (2026-10-18): both allowed, the nearest registered workspace owns the task trees (§1).
