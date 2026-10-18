# 16 - Orchestration broker: one MCP server per user, workspaces, projects, mail

- **Short:** Orchestration broker

> **Derived from:** [`../specs/orchestration-broker-mcp.md`](../specs/orchestration-broker-mcp.md) (draft 4, v1 scope, owner decisions Q-a on-demand start and Q-c nesting, placement rule). Read the spec first; this plan does not repeat it. Reviews: `../_reviews/2026-10-18-*`. Prerequisite fixes on the current engine are emergent tasks T026, T027, T028 (spec §8 step 1).

## Tasks (One Task = One Commit)

### 16.1 - MCP client spike: minimal broker and stdio shim used from Claude Code, Kilo and Codex

- **Status:** `open` · **Short:** MCP client spike · **Size:** M · **Kind:** investigation · **Depends on:** - · **Repo:** `ai-orchestration/`
- **Goal:** the spec §8 step 2 gate. A throwaway-quality broker (`ai-orch broker serve`, streamable HTTP on localhost with the UI token) and stdio shim (`ai-orch mcp`, immediate `initialize`, `broker.launch.lock`, readiness file) exposing two read tools (`whoami`, `tasks.list` for an explicit project path) and one slow tool (`debug.sleep`, for long-call behaviour).
- **Verification:** with ISOLATED client configs only (never the real `~/.claude`, `~/.kilo`, `~/.codex`, `~/.config/kilo`): each of Claude Code, Kilo and Codex lists and calls the tools; two shims started at once launch one broker; broker killed and restarted mid-session → the client recovers or the failure mode is recorded; a notice appended to text content is visible to the model. Report in `tasks/16-orchestration-broker/notes/16.1-client-spike.md` with a go / amend verdict per client.

### 16.2 - Shared on-disk locks, CAS and idempotency keys in the engine

- **Status:** `open` · **Short:** Shared locks and idempotency · **Size:** M · **Depends on:** T026 · **Repo:** `ai-orchestration/`
- **Goal:** spec §2 "Locks are on disk": every task mutation (CLI or broker) under `tasks/.ai-orch.lock` with file-hash CAS; idempotency keys with stored terminal results for mutating calls; broker singleton (`broker.lock`) and the CLI's routing rule (lock held → through the broker or "busy"; never an HTTP-timeout guess); `config_lock` CAS for setup/ensure (C7).

### 16.3 - Registry: workspace uuid/slug, explicit projects, nesting, discover

- **Status:** `open` · **Short:** Workspace and project registry · **Size:** M · **Depends on:** 16.2 · **Repo:** `ai-orchestration/`
- **Goal:** spec §1–§2: `[workspace] uuid, id`, `[[workspace.projects]]`, the nesting rule (nearest registered workspace owns the trees; sub-workspaces listed read-only), registry in SQLite under the global config dir (respects `AI_ORCHESTRATION_CONFIG`), path move with confirmation, symlink/inode checks, `projects discover` proposing entries only.

### 16.4 - QualifiedTaskRef, coordinates: links and the placement rule

- **Status:** `open` · **Short:** Qualified refs and coordination · **Size:** M · **Depends on:** 16.3 · **Repo:** `ai-orchestration/`
- **Goal:** one parser/canonicaliser for `[workspace:][project/]ID` (malformed prefixes are errors); `coordinates:` on workspace-tree tasks resolved read-only to project tasks; `validate` placement warnings; `tasks move ID --to-project P` with preview and a pointer left behind; on-disk `depends-on` unchanged.

### 16.5 - Broker MCP tools: reads, then deterministic writes

- **Status:** `open` · **Short:** Broker MCP tools · **Size:** L · **Depends on:** 16.1, 16.2, 16.4 · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/`
- **Goal:** spec §3: the broker from the UI backend; read tools; deterministic writes applied directly with optional `expect_hash`, `preview: true`, idempotency keys; `confirm_token` only for destructive/owner-facing actions; lazy console binding with explicit workspace/project (never the broker's cwd); `ai-orch mcp --local`.

### 16.6 - Skills switched to the broker

- **Status:** `open` · **Short:** Skills use the broker · **Size:** M · **Depends on:** 16.5 · **Repo:** `ai-orchestration/` + `kilo-mcp/`
- **Goal:** spec §7: generic templates and bindings tell sessions to use the broker tools, `orchestrator.ask` for formalisation and state updates, the citation rule with qualified refs, `unread_mail`; CLI instructions kept as fallback; MCP registration of the shim offered by the Doctor/setup (preview, never silent).

### 16.7 - Orchestrator workers inside the broker; recovery; orchestrator.ask tickets

- **Status:** `open` · **Short:** Broker-hosted orchestrators · **Size:** L · **Depends on:** 16.5, T027, T028 · **Repo:** `ai-orchestration/`
- **Goal:** spec §2 recovery and §4: per-workspace serialised workers in the broker, detached children with persisted pid/session/log, re-attachment on restart, `outcome_unknown` for interrupted mutations, `broker stop --drain`, trigger evaluation moved in (old daemon lock held), `orchestrator.ensure`, durable `orchestrator.ask` tickets.

### 16.8 - Mail: workspace orchestrators, then consoles; UI

- **Status:** `open` · **Short:** Workspace mail · **Size:** L · **Depends on:** 16.7 · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/` + `vscode-ai-orchestration/`
- **Goal:** spec §5–§6: mail to workspace orchestrators with metadata-only quarantine and owner acceptance, policy and limits, automatic replies on decline/expiry, `mail.fetch_ref`; then console mailboxes (lease, uuid+secret, unique names, `console_gone`); UI mail view; VS Code parity.

### 16.9 - Interface: project view and common workspace view

- **Status:** `open` · **Short:** Project and workspace views · **Size:** L · **Depends on:** 16.4, 16.5 · **Repo:** `ai-orchestration-ui/` + `vscode-ai-orchestration/`
- **Goal:** spec §7b: project selector and project view (today's views, bare ids); common workspace view with qualified ids, project column/filters/grouping, coordination tasks expanding into the project tasks they coordinate, workspace-wide questions/inbox/runs/mail with a project column, writes routed to the item's project; remembered view per window; deep links `workspace:project/ID`; then the read-only all-workspaces overview. VS Code: the same views through the bridge and a project picker in the tree views.
