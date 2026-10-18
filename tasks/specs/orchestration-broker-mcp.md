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
- **Nesting:** a project belongs to exactly one workspace. A folder can be a project of an outer workspace **or** a
  workspace of its own, not both (owner question Q-c).
- **Qualified references (C2-5, G2-3):** one grammar, `QualifiedTaskRef = [workspace ":"] [project "/"] ID`, with a
  single parser/canonicaliser in the engine. Malformed prefixes are errors, never prose. **v1 scope:** the broker and
  chat use qualified refs for addressing and citation (`ai-coding-tools:ai-orchestration/T025 (short title field)`);
  on-disk `depends-on` stays project-local (bare ids) — cross-project dependencies are v2, so the existing parsers and
  `validate` are untouched in v1.

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
- Start: on demand by the shim/CLI/UI, or at login (owner question Q-a).

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

## 8. Migration (v1), each step independently shippable (C2-9)

1. **Invariants first:** T026, T027, T028; `status` read-only; config CAS under `config_lock` (C7).
2. **MCP client spike (gate):** a minimal broker + stdio shim with two read tools, exercised from Claude Code, Kilo and
   Codex: simultaneous shim starts, broker down/up, reconnect, long tickets, text-content notices. The plan continues
   only if all three work; otherwise the spec is amended.
3. Shared on-disk locking and idempotency keys in the engine; broker singleton and readiness.
4. Registry: workspace uuid/slug, explicit projects, `projects discover` (proposals only), `QualifiedTaskRef` parser.
5. Read-only broker tools; then deterministic writes (CAS, idempotency, confirm tokens for destructive actions).
6. Skills switched incrementally to the broker, CLI fallback kept.
7. Orchestrator workers inside the broker, recovery/re-attachment, `orchestrator.ask` tickets.
8. Mail to workspace orchestrators (metadata-only quarantine, policy, limits); then consoles; UI mail view and
   workspace/project switcher.

**v2 (not now):** cross-project `depends-on` and graphs, automatic classifier turns, reactive notifications,
attachments, other machines.

## 9. Open questions for the owner

- Q-a: start the broker at login (launchd unit) or only on demand (first shim/CLI/UI use)?
- Q-c: may a folder be both a project of an outer workspace and a workspace of its own (for example `ai-orchestration`
  opened alone), with the nesting rule deciding, or must it be one or the other?
