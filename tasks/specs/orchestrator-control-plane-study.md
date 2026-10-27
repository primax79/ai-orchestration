# Study: Cross-Workspace Orchestrator Control Plane, Feedback, Handoff & Registry Consistency (T073)

- **Status:** draft for review (2026-10-27)
- **Task:** `T073 (Studio pannello orchestratori)`
- **Sources:** `N071`, `N068`, `N069`, `N070`
- **Related specs:** `ui-multi-project.md`, `orchestration-broker-mcp.md`, `orchestration-extension-spec.md`, `events-and-triggers.md`, `control-plane-safety.md`, `peer-messaging.md` (superseded)
- **Related use cases:** `UC028`, `UC030`, `UC033`, `UC034`, `UC037`
- **Open tasks evaluated for absorption:** `T070`, `T071`, `T072`, `16.7`, `16.8`

---

## Executive Summary & Core Recommendation (10-Line Synthesis)

1. **Identity by Provider Session ID:** Treat `provider_session_id` (UUID/`ses_...`) as the immutable session identity and agent names (`ai-coding-tools-d8`) as mutable `display_name` metadata; re-registering the same `provider_session_id` updates `display_name` and `last_seen` in place without bumping `generation`.
2. **Unified Liveness Model:** Unify `orchestrator status` and `sessions role` so both compute liveness from a single function combining process-table/transcript mtime probes (for interactive and headless sessions) with explicit heartbeats, eliminating the active-vs-stale contradiction.
3. **Piggybacked Feedback & Fencing:** Every `ai-orch` CLI command and broker MCP tool response checks the workspace's `orchestrator.json` and appends a one-line notice when the role is `missing`, when the caller is `fenced_out` (superseded by generation `N+1`), or when `unread_mail > 0`.
4. **First-Class Interactive & Headless Succession:** Extend `orchestrator reassign` and `rotate` (and `UC028`) to support `--kind interactive|headless`, `--provider-session-id <id>`, and `--bind-current` in a single atomic generation bump (`N -> N+1`), never fabricating a `provider_session_id` before a headless turn actually runs.
5. **Reconciled Registry & macOS APFS Fix:** Keep SQLite (`registry.sqlite`) as the cross-workspace index synced with per-workspace `.ai-orchestration/orchestrator.json`, drop raw `st_dev` comparison on macOS (which invalidates all workspaces after an APFS reboot), forward `--config-dir` into `find_project_config_path()`, and add `ai-orch workspace gc` to purge test leftovers.
6. **Top-Level "Workspaces Fleet" View:** Add a 5th top-level view (`Workspaces` / Fleet Control Plane) to `ai-orchestration-ui` and the `vscode-ai-orchestration` dashboard (plus a `Workspaces` sidebar TreeView) showing all registered and auto-discovered workspaces, their orchestrator holder/liveness, live consoles, queues, questions, verifications, and mail.
7. **Fix Multi-Project Orchestrator Scoping:** Fix `ai-orchestration-ui/backend/server.py` and `vscode-ai-orchestration/src/views/dashboard-panel.ts` so `orchestrator` and `sessions` endpoints always bind to the workspace root (`state.workspace`), never to a child project (`state.project_root`).
8. **Zero Cross-Session Permission Laundering:** Messages or handoff requests from the panel or another workspace never execute shell/file mutations directly; unattended orchestrators receive metadata-only mail until owner acceptance, and nudges to interactive consoles are framed as untrusted data requiring the human operator's turn approval.

---

## 1. Problem and Empirical Evidence (Observed State on 2026-10-27)

On 2026-10-27, the owner observed that there is no single place to see which workspace has an orchestrator, whether that orchestrator is alive, which interactive sessions are running across workspaces, or how to hand off / reassign the orchestrator role cleanly. Inspecting the live machine state read-only reveals four mutually inconsistent views of reality.

### 1.1 Workspace Registry (`ai-orch workspace list --json`)

Running `./bin/ai-orch workspace list --json` (under the default non-interactive shell where `/usr/bin/python3` is Python 3.9, and under `/opt/homebrew/bin/python3` 3.11+) returns 6 registered workspaces:

```json
{
  "ok": true,
  "items": [
    {
      "uuid": "52c62ed7-47c6-45e0-8136-6aa92350e4de",
      "slug": "ai-coding-tools",
      "title": null,
      "canonical_path": "/Users/Alfredo/works/ai-coding-tools",
      "device": 16777231,
      "inode": 329323713,
      "registered_at": "2026-10-21T08:29:08.434503+00:00",
      "last_seen": "2026-10-21T08:29:08.434503+00:00",
      "stale": true
    },
    {
      "uuid": "11f60ceb-4d07-4248-8616-41cdf5db2fcd",
      "slug": "d4science-local-env",
      "title": "D4Science local environment",
      "canonical_path": "/Users/Alfredo/works/d4science_local_env",
      "device": 16777234,
      "inode": 417546704,
      "registered_at": "2026-10-24T08:19:11.527520+00:00",
      "last_seen": "2026-10-24T08:19:11.527520+00:00",
      "stale": false
    },
    {
      "uuid": "8d82eeb8-2917-443d-a64f-da89696f841b",
      "slug": "d4science-python-library",
      "title": null,
      "canonical_path": "/Users/Alfredo/works/d4science-python-library",
      "device": 16777231,
      "inode": 412183655,
      "registered_at": "2026-10-20T17:57:03.790278+00:00",
      "last_seen": "2026-10-20T17:57:03.790278+00:00",
      "stale": true
    },
    {
      "uuid": "03fba38e-4b73-49ee-b707-b003ebfc7eec",
      "slug": "dave-agent",
      "title": null,
      "canonical_path": "/Users/Alfredo/works/dave_agent",
      "device": 16777234,
      "inode": 138870026,
      "registered_at": "2026-10-27T08:21:52.783204+00:00",
      "last_seen": "2026-10-27T08:21:52.783204+00:00",
      "stale": false
    },
    {
      "uuid": "cea9cb8f-3b8c-4ca7-b36c-042ebf07fa6a",
      "slug": "porting-liferay",
      "title": "Liferay porting and social SG4",
      "canonical_path": "/Users/Alfredo/works/gcube/porting_liferay",
      "device": 16777234,
      "inode": 203951573,
      "registered_at": "2026-10-24T08:19:11.268899+00:00",
      "last_seen": "2026-10-24T08:19:11.268899+00:00",
      "stale": false
    },
    {
      "uuid": "9d41faf5-8be3-481e-aa11-80ad9bb32ab3",
      "slug": "smartgears4-migration",
      "title": null,
      "canonical_path": "/Users/Alfredo/works/smartgears4_migration",
      "device": 16777234,
      "inode": 383753166,
      "registered_at": "2026-10-22T10:22:24.380114+00:00",
      "last_seen": "2026-10-24T08:19:18.138258+00:00",
      "stale": false
    }
  ]
}
```

**Two bugs uncovered in `list_workspaces` (`scripts/orchestration_registry.py:988-1005`):**
1. **macOS APFS `st_dev` drift across reboots:** `ai-coding-tools` and `d4science-python-library` were registered on Oct 20–21 when the root volume's `st_dev` was `16777231`. After a reboot, macOS assigned `st_dev = 16777234` to the same APFS volume. Even though `canonical_path` exists, `st_ino` matches (`329323713` and `412183655`), and `orchestration.toml`'s `[workspace] uuid` matches, `cur_st.st_dev != d["device"]` permanently marks both workspaces `stale: true`.
2. **Python 3.9 `tomllib` silent exception:** When invoked without `/opt/homebrew/bin` in `PATH`, `/usr/bin/python3` (3.9) has `tomllib = None`. `load_toml_file()` raises `RuntimeError`, which `list_workspaces()` catches with a bare `except Exception: stale = True`, reporting **all 6 workspaces** as `stale: true`.

### 1.2 Project Config Directory (`ls ~/.config/ai-orchestration/projects`)

Listing `~/.config/ai-orchestration/projects` reveals 11 directories:

```text
ai-coding-tools
d4science-python-library
d4science_kb
d4science_local_env
dave_agent
porting_liferay
smartgears4_migration
test_orchestrator_reassign_end0
test_ws
workspace
ws
```

- `d4science_kb` has `orchestration.toml` (written by `orchestrator reassign`), `.ai-orchestration/orchestrator.json`, and 3 session records, but **is not registered** in `registry.sqlite`.
- Four directories (`test_orchestrator_reassign_end0`, `test_ws`, `workspace`, `ws`) are **test leftovers** written to the user's real `~/.config/ai-orchestration/projects/` because:
  - `plan_workspace_register()` (`scripts/orchestration_registry.py:676`) and `plan_projects_discover()` (`line 1195`) call `find_project_config_path(canonical)` without passing `config_dir` (`--config-dir "$T/cfg"`), so `UC030`/`UC033`/`UC034` probes and unit tests that pass `--config-dir` without setting `AI_ORCHESTRATION_CONFIG` write their `[workspace]` TOML into `~/.config/ai-orchestration/projects/<temp_dir_name>/orchestration.toml`.
  - `test_orchestrator_reassign_end0` was created by a pytest `tmp_path` test calling `orchestrator reassign` without isolating `AI_ORCHESTRATION_CONFIG`.

### 1.3 Per-Workspace Orchestrator Status, Sessions & Live Claude Code Sessions

Scanning all 20 folders under `~/works/*` and `~/works/gcube/*` that contain `tasks/` or `.ai-orchestration*` and comparing them with the 7 live Claude Code sessions reported by Claude's `ListAgents` (`ai-coding-tools-d8`, `ai-coding-tools-ea`, `porting-liferay-6d`, `porting-liferay-56`, `dave-agent-92`, `d4science-python-library-1b`, `d4science-kb-3d`):

| Workspace Path | In SQLite Registry? | `orchestrator status` | `sessions list` (active / total) | Live Claude Sessions (`ListAgents`) | Discrepancy Summary |
| --- | --- | --- | --- | --- | --- |
| `~/works/ai-coding-tools` | Yes (`stale: true` due to `st_dev`) | `active`, gen 2, `claude`, `session_id: ai-coding-tools-d8`, `provider_session_id: 5865a698-...` | 0 active, 1 `stale` (`ai-coding-tools-d8`, gen 2), 1 `retired` (`ai-coding-tools-c1`, gen 1) | `ai-coding-tools-d8` (orchestrator), `ai-coding-tools-ea` | `orchestrator status` says `active`, `sessions list` says `stale` (>300s since registration); `ai-coding-tools-ea` unknown; rename `c1 -> d8` forced gen 1 -> 2 |
| `~/works/d4science_kb` | **No** (only in `projects/d4science_kb`) | `active`, gen 3, `claude`, `session_id: f40e1f4e-...`, `provider_session_id: 9063f48c-...` | 0 active, 1 `stale` (gen 3 interactive), 2 `retired` (gen 2 phantom headless `f5f121da`, gen 1 kilo `ses_e9b...`) | `d4science-kb-3d` (orchestrator) | Unregistered in SQLite; `orchestrator status` says `active` while `sessions list` says `stale`; N068 created phantom headless gen 2 |
| `~/works/smartgears4_migration` | Yes (`active`) | `active`, gen 1, `kilo`, `session_id: cc1dd376-...`, `provider_session_id: ses_e9d0...` | 0 active, 1 `stale` (last seen `2026-10-22T10:22:24Z`, 5 days ago!) | None | `orchestrator status` claims `active` for a session dead for 5 days (`orchestrator.json` never checks staleness) |
| `~/works/d4science-python-library` | Yes (`stale: true` due to `st_dev`) | `missing` | `[]` | `d4science-python-library-1b` | Live interactive session is unregistered; workspace has 4 child projects |
| `~/works/dave_agent` | Yes (`active`) | `missing` | `[]` | `dave-agent-92` | Live interactive session is unregistered (also has 2 worktrees `dave_agent-wt-*`) |
| `~/works/gcube/porting_liferay` | Yes (`active`) | `missing` | `[]` | `porting-liferay-6d`, `porting-liferay-56` | Two live interactive sessions, neither registered, no orchestrator |
| `~/works/d4science_local_env` | Yes (`active`) | `missing` | `[]` | None | Registered, has `tasks/` and `.ai-orchestration/events`, no orchestrator |
| `~/works/gcube_audit` | **No** | `missing` | `[]` | None | Has `tasks/`, `.ai-orchestration/events`, and `.ai-orchestration/orchestration.toml` (ignored path!) |
| `~/works/d4science-keycloak` | **No** | `missing` | `[]` | None | Has `tasks/` and `.ai-orchestration/events` |
| `~/works/d4science-evolution-assurance` | **No** | `missing` | `[]` | None | Has `tasks/`, `.ai-orchestration/events`, `.ai-orchestration/idempotency` |
| `~/works/gcube_atlas` | **No** | `missing` | `[]` | None | Has `tasks/` and `.ai-orchestration/events` |
| `~/works/ricerca_auto` | **No** | `missing` | `[]` | None | Has `tasks/` and `.ai-orchestration/events` |
| `~/works/ansible`, `app-nea`, `audit_project-claude`, `gcube_audit_g4`, `ngx-gcube`, `gcube/liferay62` | **No** | `missing` | `[]` | None | Have `tasks/`, no `.ai-orchestration/` |

### 1.4 The Three Concrete Friction Cases from 2026-10-27

1. **Case N068 (`d4science_kb` phantom headless session & double generation bump):**
   - `d4science_kb` had a stale gen 1 interactive Kilo holder (`ses_e9bdf3ba5ffeyIjRCwCFIEeG4M`, last seen 2026-10-22, 0 turns).
   - To make the current interactive Claude session (`9063f48c-47d4-4079-8d84-bd8e25babd33`, display name `d4science-kb-3d`) the orchestrator, the session ran `ai-orch orchestrator reassign --tool claude --model claude-opus-5-5 --no-handoff --expect-hash <hash>`.
   - `reassign_orchestrator()` called `rotate_orchestrator()`, which hardcoded `kind="headless"` and generated a random UUID `cand_prov_id = str(uuid.uuid4())` (`a168b9a6-4ffd-4434-972d-2b4588434bfa`). Because `--no-handoff` was used, no `claude` process ever ran with `--session-id a168b9a6-...`, leaving a phantom headless holder at generation 2 pointing to a non-existent Claude transcript.
   - The session then had to run `ai-orch sessions register --tool claude --kind interactive --role orchestrator --provider-session-id 9063f48c-...`, bumping to generation 3.
2. **Case N069 (`config show` ignores cwd & `reassign --dry-run` hides target path):**
   - Running `ai-orch config show` inside `~/works/d4science_kb` printed `Project config: None (exists=False)` because `orchestration_config.py` sets `--workspace` default to `None` instead of `.` (unlike `orchestrator` and `sessions`).
   - Running `ai-orch orchestrator reassign --dry-run` printed diff headers `--- a/orchestration.toml` / `+++ b/orchestration.toml` (`scripts/orchestration_orchestrator.py:2054-2055` uses `f"a/{target_path.name}"`), hiding that it actually writes `~/.config/ai-orchestration/projects/d4science_kb/orchestration.toml`.
3. **Case N070 + Session Rename (`ai-coding-tools-c1` -> `ai-coding-tools-d8`):**
   - The interactive Claude session orchestrating `ai-coding-tools` worked for days without registering because nothing in `AGENTS.md`, `orchestration-workflow`, or CLI outputs prompted it to register (`N070`/`T071`).
   - Once registered as `--session-id ai-coding-tools-c1 --provider-session-id 5865a698-40a0-4f69-ad79-2e3ace4f7ffa` (gen 1), an account switch caused Claude Code to rename the live session from `ai-coding-tools-c1` to `ai-coding-tools-d8` while keeping the exact same `provider_session_id` (`5865a698-40a0-4f69-ad79-2e3ace4f7ffa`).
   - Because `register_session()` (`scripts/orchestration_sessions.py:272`) checks `if old_sess_id and old_sess_id != reg_session_id:` instead of checking whether `provider_session_id` is the same session, re-registering with the new name bumped `generation` 1 -> 2 and retired `ai-coding-tools-c1`.

---

## 2. Existing Pieces and Gaps, Options, and Recommendations (Per Topic of N071)

### Topic 1: Orchestrator Feedback, Liveness & Session Identity

#### Existing Pieces
- `<workspace>/.ai-orchestration/orchestrator.json`: stores `generation`, `cursor`, `delivery_cursor`, `trigger_scan_cursor`, `status`, and `current` (`role_id`, `generation`, `registry_session_id`, `session_id`, `provider_session_id`, `tool`, `model`, `started`, `turns`, `last_usage`, `status`).
- `<workspace>/.ai-orchestration/sessions/<session_id>.json`: stores session records; `compute_session_status()` marks a session `stale` when `now - last_seen > 300s` (`DEFAULT_STALE_TIMEOUT_SEC`).
- `<workspace>/.ai-orchestration/orchestrator/worker.json`: checked by broker `orchestrator.status` (`ai-orchestration-ui/backend/broker/server.py:1455`) for `alive` and `heartbeat_at`.

#### Gaps
1. **Split status calculation:** `get_orchestrator_status()` (`scripts/orchestration_orchestrator.py:840`) returns `orch_doc.get("status", "active")` verbatim without checking the holder session's `last_seen` or process/transcript liveness. Thus `smartgears4_migration` reports `status: "active"` in `orchestrator status` despite its holder session being untouched since 2026-10-22.
2. **Unstable session names used as primary keys:** Claude Code (`ListAgents`) assigns `<workspace>-<2-hex-chars>` names that change across account switches or restarts while the underlying transcript UUID (`provider_session_id`) stays fixed. Conversely, `register_session` keys files by `reg_session_id`.
3. **No passive liveness for interactive sessions:** Interactive sessions cannot run a background heartbeat loop while waiting for user input. Relying solely on explicit `sessions heartbeat` calls with a 300s timeout guarantees every interactive orchestrator shows as `stale` while idle between user prompts.
4. **No provider-session correlation:** The engine does not inspect local provider state (Claude's `~/.claude/projects/<escaped-cwd>/<provider_session_id>.jsonl` mtime, Kilo's session store, Codex's `~/.codex/sessions/`) to verify whether a `provider_session_id` actually exists on disk or when its last turn occurred.
5. **Silent role loss / missing role:** Sessions running `ai-orch` commands or MCP tools receive no feedback when the workspace has no orchestrator (`T071`) or when their session was superseded by a newer generation.

#### Options & Trade-offs

- **Option 1A (Explicit Heartbeat Only + Longer Timeout):** Keep liveness purely based on `sessions heartbeat` and piggyback automatic `heartbeat` on every `ai-orch` CLI / MCP call made by that session, raising the interactive stale threshold to e.g. 2 hours.
  - *Pros:* Zero provider-specific file/process probing; simple.
  - *Cons:* An interactive session that crashed or closed 5 minutes ago looks `active` for 2 hours; an interactive session open in a terminal while the owner reads docs for 3 hours looks `stale`; cannot detect phantom `provider_session_id`s (`N068`).
- **Option 1B (Hybrid Liveness: Auto-Heartbeat on CLI/MCP + Provider Transcript & Process Probe — Recommended):**
  1. **Identity separation:** `registry_session_id` is a stable UUID generated once per `(tool, provider_session_id)` pair; if `register_session` is called with a `provider_session_id` that already matches an existing non-retired session in the workspace (or the current orchestrator holder), it **updates** that session in place (updating `display_name`, `last_seen`, `cwd`, `model`) without bumping `generation`.
  2. **Three-tier liveness check (`compute_liveness`):**
     - **Headless worker:** checks `worker.json` PID via `is_process_alive(pid, expected_start_time)` + turn lease.
     - **Interactive or headless session:** checks (a) `last_seen` updated automatically on any `ai-orch` CLI / MCP call carrying the session's ID/env, (b) provider transcript file existence and mtime on disk (e.g. `~/.claude/projects/*/<provider_session_id>.jsonl` for Claude; Kilo/Codex session files), and (c) OS process table probe (`ps` matching `--resume <id>` or active tool进程 with `cwd` = workspace).
     - Status values unified across `orchestrator status`, `sessions role`, and UI: `missing` | `active` (seen/transcript < 15m or live process) | `idle` (interactive, process/transcript exists, quiet 15m–24h) | `stale` (no process and quiet > threshold) | `paused` | `rotating` | `retired`.
  3. **Piggybacked CLI & MCP Role Feedback (absorbs T071):**
     - Every mutating or task-querying `ai-orch` CLI command and every broker MCP tool response checks `orchestrator.json` (read-only, zero lock).
     - If `status == "missing"`, prints/appends a one-line hint: `[ai-orch] No orchestrator registered for <ws>. If you are orchestrating, run: ai-orch orchestrator claim --kind interactive --tool <tool> (or ai-orch orchestrator ensure)`.
     - If the caller identifies itself (via `--actor` / `--session` / `AI_ORCH_SESSION_ID` / MCP console binding) and was previously the orchestrator (`retired` by a newer `generation`), prints/appends a prominent warning: `[ai-orch] ROLE LOST: session <id> was superseded by generation <N> (<holder>, reason: <reason>). Stop orchestrating immediately.`

**Recommendation:** **Option 1B**. It solves the `c1 -> d8` rename bug, detects phantom session IDs immediately (`transcript_exists: false`), distinguishes `idle` interactive windows from dead/stale ones, and unifies `orchestrator status` with `sessions role`.

---

### Topic 2: Handoff and Reassignment (Headless & Interactive)

#### Existing Pieces
- `rotate_orchestrator()` (`scripts/orchestration_orchestrator.py:1803`) and `reassign_orchestrator()` (`line 1991`): implement fenced succession (`active -> rotating -> active`) with `fencing_token`, config update (`routing.default_orchestrator`), and `build_handoff_prompt()` (`line 1183`).
- `UC028`: specifies headless queue and succession handoff.

#### Gaps
1. **Hardcoded headless assumption & phantom sessions (`N068`):** `rotate_orchestrator()` always registers a new `kind="headless"` session with a random `cand_prov_id` even when `--no-handoff` is passed or when the owner wants to assign the role to a running interactive session (`T070`).
2. **Five succession transitions exist in real usage, but only one is supported:**
   - `missing -> interactive` (claiming an empty workspace from an interactive session)
   - `headless -> interactive` (owner takes over from headless worker in an interactive Claude/Kilo/Codex window)
   - `interactive -> interactive` (switching from a stale Kilo interactive session to a live Claude interactive session, as in `d4science_kb` `N068`, or handing off between two windows)
   - `interactive -> headless` (handing an interactive session's work back to the background worker queue)
   - `headless -> headless` (context rotation or tool switch, today's `UC028`)
3. **Fencing for interactive holders:** When an interactive holder is superseded (by another window or by the owner from the UI panel), nothing fences its subsequent `tasks transition` or `run start` calls, and there is no documented protocol for what a fenced-out interactive session must do.

#### Options & Trade-offs

- **Option 2A (Separate Commands: `orchestrator reassign` for Headless, `sessions register --role orchestrator` for Interactive):** Keep `orchestrator reassign` strictly headless and tell interactive sessions to use `sessions register --role orchestrator` plus `config set-routing`.
  - *Pros:* Minimal change to `orchestration_orchestrator.py`.
  - *Cons:* Fails the mental model that caused `N068`; requires two separate commands (and two locks/events) to update `orchestration.toml` routing and rotate the role holder; skips fenced succession (`fencing_token`) and handoff prompt generation for interactive sessions.
- **Option 2B (Unified Fenced Succession in `orchestrator reassign` / `claim` / `hand-off` — Recommended):**
  Extend `reassign_orchestrator()` and `rotate_orchestrator()` (absorbs `T070` and `T072`) so `kind` (`headless` | `interactive`) is a first-class parameter of the role holder:
  1. **Target specification flags on `orchestrator reassign` (and new alias `orchestrator claim`):**
     - `--kind interactive|headless` (default: `interactive` if `--provider-session-id` or `--bind-current` is given; otherwise `headless`).
     - `--provider-session-id <id>` (or `--bind-current`, which auto-detects the calling session's provider ID from env/transcript in `cwd`).
     - `--display-name <name>` (e.g., `d4science-kb-3d`, stored in `metadata.display_name` and `current.display_name`).
  2. **Single generation bump (`N -> N+1`), zero phantom sessions:**
     - If `kind == "interactive"`: verifies that `--provider-session-id` (if given) corresponds to a real transcript on disk (unless `--force`), updates `orchestration.toml` (with real path in diff headers `a/<full-or-tilde-path>`, fixing `N069`/`T072`), retires generation `N` with `reason`, registers the interactive session as generation `N+1` in a **single atomic transition**, and outputs the generated `handoff_prompt` in the JSON/stdout result so the interactive session immediately ingests the on-disk state summary without spawning a separate headless subprocess.
     - If `kind == "headless"` and `--no-handoff`: sets `provider_session_id = null` (`pending_first_turn`) instead of fabricating a fake UUID before `claude -p` has ever run. The real `provider_session_id` is recorded only when the first turn actually executes and creates the transcript.
  3. **Fencing enforcement & fenced-out protocol:**
     - `orchestrator.json` increments `generation` and records `fencing_token` and `previous_holder: {session_id, provider_session_id, display_name, tool, retired_at, reason}`.
     - Any mutating command (`tasks`, `questions`, `inbox`, `run`, `orchestrator`) where the caller passes `--orchestrator-gen <g>` (or is matched by `AI_ORCH_SESSION_ID` / `provider_session_id` to a retired orchestrator session) is **refused with error code `fenced-out-orchestrator`** if it attempts an orchestrator-only action, and receives a mandatory banner in stdout/MCP text.
     - **Contract for a fenced-out session (in `orchestration-workflow` skill & `AGENTS.md`):** Upon seeing `fenced-out-orchestrator` or the `ROLE LOST` notice, the session must (1) stop dispatching/transitioning tasks as orchestrator, (2) finish or cleanly report any in-flight tool call, and (3) inform the user in one line that generation `N+1` now holds the orchestrator role.

**Recommendation:** **Option 2B**. It directly resolves `N068` (`T070`) and `N069` (`T072`), eliminates phantom sessions, supports all 5 succession paths with a single generation bump, and gives interactive sessions the same file-derived handoff context as headless ones.

---

### Topic 3: Cross-Workspace Panel (State, Messaging, Actions)

#### Existing Pieces
- `ui-multi-project.md` (16.9, delivered): adds a project switcher (`All projects` Common View vs single project) inside **one** bound workspace.
- `orchestration-broker-mcp.md` §3b & §7b: defines `workspaces.list` (returning `uuid, slug, title, path, orchestrator, unread_mail`), `orchestrator.status`, `orchestrator.ask`, and `mail.*` (16.7 / 16.8), and mentions a read-only "all workspaces" overview.
- `UC033` (`ai-orch tasks next --workspace <ws> --all-projects`) and `UC037` (`ai-orch tasks verification-queue --all-workspaces`).

#### Gaps
1. **No cross-workspace UI or CLI rollup:** The owner has 13+ active/recent workspaces under `~/works/`. Today, checking their state requires running `orchestrator status`, `sessions list`, `tasks next`, `questions list`, `inbox list`, and `tasks verification-queue` across 13 directories by hand.
2. **Unregistered workspaces are invisible:** `ai-orch workspace list` only queries SQLite (`6` rows), missing `d4science_kb`, `gcube_audit`, `d4science-keycloak`, `d4science-evolution-assurance`, `gcube_atlas`, `ricerca_auto`, `ansible`, etc.
3. **Interactive sessions (`ListAgents` / consoles) are invisible:** Live interactive sessions (`porting-liferay-6d`, `porting-liferay-56`, `dave-agent-92`, `d4science-python-library-1b`, `ai-coding-tools-ea`) do not appear in any panel.
4. **No interactive control actions from the overview:** `orchestration-broker-mcp.md` §7b originally envisioned "all workspaces" as a *read-only* overview, but the owner's 2026-10-27 request (`N071`) explicitly asks for **an additional panel listing all existing workspaces, from which you can communicate with them and see their state**, plus handoff/reassignment.
5. **Bug in current UI backend & VS Code extension (`project_root` vs `workspace`):** In `ai-orchestration-ui/backend/server.py` (lines 4605, 5072–5430) and `vscode-ai-orchestration/src/views/dashboard-panel.ts` (lines 2474, 2901–3210), `sessions` and `orchestrator` commands pass `--workspace state.project_root(request)` instead of `state.workspace`. In a multi-project workspace (`ai-coding-tools`, `d4science-python-library`, `porting_liferay`), switching the UI dropdown to a subproject looks for `.ai-orchestration/orchestrator.json` inside the *subproject* instead of the workspace root!

#### Options & Trade-offs (Discovery & Live Session Detection)

- **Option 3A (Strict Registry Only):** Only show workspaces registered in `registry.sqlite` and sessions registered in `.ai-orchestration/sessions/`.
  - *Pros:* Fast, purely reads SQLite + registered JSON files.
  - *Cons:* Fails on today's real machine state where 7+ real workspaces (`d4science_kb`, `gcube_audit`, etc.) and 5 of 7 live Claude Code sessions are unregistered.
- **Option 3B (Registry + Root Scan + Provider Transcript Discovery — Recommended):**
  Combine three sources into one `ai-orch workspace fleet [--scan-root ~/works] --json` (and `/api/fleet` / broker `workspaces.fleet`) call:
  1. **Registered workspaces** from `registry.sqlite` (with `st_dev` false-positive fixed).
  2. **Unregistered workspace candidates** discovered by scanning configured scan roots (default: parent directory of registered workspaces or `~/works`, configurable via `[discovery] workspace_roots = ["~/works", "~/works/gcube"]` in global `orchestration.toml`) up to depth 2 for folders containing `tasks/00-INDEX.md`, `.ai-orchestration/`, or `.ai-orchestration.local.toml` (excluding `.kilo/worktrees`, `*-wt-*` git worktrees, and git-ignored/test dirs). Shown with badge `unregistered` and a 1-click `Register…` action.
  3. **Live/recent provider sessions** correlated per workspace path:
     - **Registry sessions:** from `<ws>/.ai-orchestration/sessions/*.json` + `orchestrator.json`.
     - **Unregistered live/recent provider sessions (read-only local probe):** scans `~/.claude/projects/<escaped-ws-path>/*.jsonl` (reading mtime and the last entry's session UUID / slug if active within the last 24h) and running `claude`/`kilo`/`codex` OS processes by `cwd` (`lsof -a -d cwd` / `ps`). Any live session not yet in `.ai-orchestration/sessions/` appears in the panel as `unregistered console` with a 1-click **"Bind as Orchestrator…"** or **"Register Console"** action!

**Recommendation:** **Option 3B**, plus fixing `server.py` and `dashboard-panel.ts` so `orchestrator` and `sessions` always target the workspace root (`state.workspace`).

---

### Topic 4: Registry Consistency and Cleanup

#### Existing Pieces
- Global SQLite registry: `~/.config/ai-orchestration/broker/registry.sqlite` (`workspaces`, `projects`).
- Global per-project config store: `~/.config/ai-orchestration/projects/<folder-name>/orchestration.toml`.
- Workspace-local config: `<ws>/.ai-orchestration.local.toml`.
- Workspace-local runtime state: `<ws>/.ai-orchestration/orchestrator.json` and `<ws>/.ai-orchestration/sessions/*.json`.

#### Gaps
1. **Four disconnected stores:**
   - `orchestrator reassign` writes `~/.config/ai-orchestration/projects/d4science_kb/orchestration.toml` and `<ws>/.ai-orchestration/orchestrator.json`, without registering `d4science_kb` in `registry.sqlite` or writing `[workspace] uuid, id`.
   - `find_project_config_path(ws)` keys `~/.config/ai-orchestration/projects/<ws.name>/` by `ws.resolve().name` (`d4science_local_env`, `porting_liferay`), whereas `registry.sqlite` keys by `slug` (`d4science-local-env`, `porting-liferay`). Worse, any temp folder named `ws` or `workspace` collides in `~/.config/ai-orchestration/projects/ws`!
   - `gcube_audit` has `<ws>/.ai-orchestration/orchestration.toml`, which `find_project_config_path()` completely ignores.
2. **Test pollution in `~/.config/ai-orchestration/projects/`:**
   - `plan_workspace_register()` and `plan_projects_discover()` do not pass `config_dir` to `find_project_config_path()`.
3. **False `stale: true` on macOS APFS:**
   - `list_workspaces()` compares `cur_st.st_dev != d["device"]`, which breaks after every macOS reboot.

#### Options & Trade-offs

- **Option 4A (Move Everything into Global SQLite):** Move `orchestrator.json`, `sessions/*.json`, and project configs into `~/.config/ai-orchestration/broker/registry.sqlite`.
  - *Pros:* Single database file for the broker.
  - *Cons:* Violates the core architectural rule ("Keep working state inside the project" and self-contained `<ws>/.ai-orchestration/` when the broker is not running).
- **Option 4B (Federated Authority with Deterministic Reconciliation & `workspace gc` — Recommended):**
  1. **Clear authority per concern:**
     - **Per-workspace runtime state (`<ws>/.ai-orchestration/orchestrator.json`, `sessions/`, `events/`, `orchestrator/queue/`):** authoritative on disk inside `<ws>/.ai-orchestration/`.
     - **Global Workspace Directory (`registry.sqlite`):** authoritative index of known workspace roots (`uuid`, `slug`, `canonical_path`, `inode`).
     - **Automatic registration bridge:** When `orchestrator start`, `orchestrator reassign`, `orchestrator ensure`, or `sessions register --role orchestrator` runs on a real workspace (not under `/tmp` or `/var/folders`), it automatically ensures the workspace has `[workspace] uuid, id` and is upserted into `registry.sqlite` (or prompts in `--dry-run`).
  2. **Fix `st_dev` check on macOS:** In `list_workspaces()` and `show_workspace()` (`scripts/orchestration_registry.py`), if `cpath.is_dir()` and `cfg_uuid == d["uuid"]` and `cur_st.st_ino == d["inode"]`, treat a changed `st_dev` as a benign mount-ID update (auto-refresh `device` in SQLite on next write) rather than marking the workspace `stale`. Mark `stale` only if `!cpath.is_dir()`, or `inode` changed (folder replaced), or `cfg_uuid` mismatches.
  3. **Fix test leakage & path resolution:**
     - Pass `config_dir` through to `find_project_config_path(ws, global_config_from_dir(config_dir))` in all `orchestration_registry.py` functions.
     - Support `<ws>/.ai-orchestration/orchestration.toml` as a recognized fallback in `find_project_config_path()` (or migrate `gcube_audit/.ai-orchestration/orchestration.toml` to `.ai-orchestration.local.toml` with a Doctor finding).
     - Refuse or warn when writing to `~/.config/ai-orchestration/projects/<name>` if `ws` is inside `$TMPDIR`, `/tmp`, `/private/var/folders`, or `pytest-of-*` while `config_dir` is the user's real home config!
  4. **Add `ai-orch workspace gc` (Preview -> Apply with `plan_hash`):**
     - Scans `~/.config/ai-orchestration/projects/*` and `registry.sqlite`.
     - Identifies orphaned project config directories whose workspace path does not exist, has no `[workspace]` link to any existing directory under `~/works`, or matches test patterns (`test_*`, `ws`, `workspace` with `demo-ws`/`test-ws`).
     - Previews moving them to `~/.config/ai-orchestration/.trash/<timestamp>/` and applies with `--apply --expect-hash`.

**Recommendation:** **Option 4B**. It preserves per-workspace portability while eliminating all four sources of registry drift and cleaning up the test leftovers safely.

---

### Topic 5: Security and Permissions (No Cross-Session Permission Laundering)

#### Existing Pieces
- `events-and-triggers.md` §0c E3: unattended event-batch turns run with `policy = "reduced_capability"` (read-only + `questions ask` + proposals; no shell, no edits, no delegation).
- `orchestration-broker-mcp.md` §6: mail to an unattended orchestrator is quarantined (metadata-only) until the owner accepts it; `[mail] isolation = open | restricted | blind`.
- `control-plane-safety.md`: localhost token auth (`X-AI-Orch-Token`), CSP, preview-then-apply with `plan_hash`.

#### Gaps
1. **Cross-session permission laundering via interactive consoles or panel messages:**
   - Suppose Session A in workspace `X` (or an automated script) sends a message to Session B in workspace `Y`, where Session B was launched by the owner with `permission_mode = bypassPermissions` (or `auto`) or has access to production credentials (e.g. `ansible`). If that message is injected directly as an executable prompt turn into Session B without owner confirmation, Session A has laundered its untrusted text into Session B's elevated permissions.
2. **Ambiguity between Owner actions in the UI vs Agent MCP calls:**
   - Both the Web UI / VS Code panel (used by the human owner) and agent sessions (via CLI or MCP shim) talk to `ai-orch` / the broker. If an agent session calls `ai-orch orchestrator reassign` or `orchestrator enqueue --type owner_chat`, it could impersonate the owner unless owner-only actions are gated or provenance-tagged.

#### Options & Trade-offs

- **Option 5A (Hard Block All Cross-Workspace Messaging to Interactive Sessions):** Only allow messages to headless orchestrators under `reduced_capability`; forbid sending messages to interactive sessions or triggering handoff/reassignment from the panel.
  - *Pros:* Eliminates interactive-session laundering completely.
  - *Cons:* Contradicts the owner's workflow where most active orchestrators today (`ai-coding-tools-d8`, `d4science-kb-3d`, `porting-liferay-6d`, `dave-agent-92`) **are** interactive sessions!
- **Option 5B (Provenance-Separated Capabilities: Owner UI Token vs Agent Console Token + Untrusted Envelope — Recommended):**
  Define a strict three-column permission matrix distinguishing (1) **Autonomous Background / Panel Read**, (2) **Agent Session Actions (CLI/MCP)**, and (3) **Owner Control-Plane Actions (UI/VS Code with Owner Confirmation)**:

| Operation | Panel Auto (No Owner Click) | Agent Session (CLI / MCP) | Owner in Panel (Preview -> Confirm) | Security Invariant |
| --- | --- | --- | --- | --- |
| Read workspace fleet, liveness, queues, counts | Allowed (read-only) | Allowed (`workspaces.list`, `orchestrator.status`) | Allowed | Zero side effects (`status` never writes or locks) |
| Heartbeat / update own `display_name` (same `provider_session_id`) | N/A | Allowed for own session | Allowed | Cannot hijack another `provider_session_id` |
| Claim `missing` orchestrator role | Never auto-claimed by UI | Allowed (`orchestrator claim`) if role is `missing` or `stale` (with audit event) | Allowed (`Assign / Claim`) | Emits `orchestrator.rotated` event visible in UI |
| Reassign / take over an **active** orchestrator | Forbidden | Requires `--force` + logs high-visibility `orchestrator.reassigned` event (or proposes to owner) | Allowed with diff preview + `expect_hash` | Active holder is fenced via `fencing_token` and notified on next call |
| Send message from **Owner in Panel** to Headless Orchestrator | Forbidden | N/A | Enqueues `owner_chat` turn (`policy = orchestrate`) | Authenticated by UI `confirm_token` / owner interaction |
| Send message from **Owner in Panel** to Interactive Console | Forbidden | N/A | Deposits in console mailbox + optional 1-line `SendMessage` nudge | Interactive session still obeys its own human turn/tool approval rules |
| Send message from **Another Workspace (Peer Agent)** to Workspace/Console | Forbidden | `mail.send`: lands in quarantine (metadata-only for headless; `<untrusted_peer_mail nonce=...>` for console) | Owner clicks **Accept & Deliver** in panel to release body to headless orchestrator | **Never** becomes `owner_chat`; headless runs under `reduced_capability`; console sees explicit untrusted-data banner and never auto-executes |
| Clean up stale/test configs (`workspace gc`) | Preview only | Preview only (`--dry-run`) | Moves to `.trash/` with `--apply --expect-hash` | Never `rm -rf`; always reversible via `.trash/` |

**Recommendation:** **Option 5B**. It lets the human owner control every workspace and communicate with both headless and interactive sessions from the panel, while guaranteeing that peer agent messages can never escalate privileges across sessions or workspaces.

---

## 3. Where the Panel Lives, Data Model & ASCII Mockup

### 3.1 Architectural Placement: Where Does the Panel Live?

There are two main options for integrating the Cross-Workspace Control Plane into `ai-orchestration-ui` and `vscode-ai-orchestration`:

- **Option P1 (Extend the Workspace Switcher Dropdown in `ui-multi-project.md`):** Add an "All Workspaces" option above "All Projects" inside the existing Task Backlog Manager view.
  - *Pros:* Reuses the existing Backlog/Kanban table.
  - *Cons:* The Task Backlog view is task-centric (columns for task ID, state, priority), whereas the owner's cross-workspace need (`N071`) is **orchestrator- and workspace-centric** (who holds the orchestrator role, liveness, live interactive consoles, unread mail, pending verifications across workspaces,inbox triage counts, handoff/reassign/message actions). Cramming 15 workspaces' tasks into one flat table loses the control-plane view.
- **Option P2 (New 5th Top-Level Macro-View "Workspaces Fleet" + VS Code Sidebar TreeView — Recommended):**
  Extend `orchestration-extension-spec.md` from 4 to **5 Macro-Responsibilities** by adding **`0. Workspaces Fleet (Cross-Workspace Control Plane)`** as a top-level navigation tab in the Web UI / VS Code Webview Dashboard (alongside *Backlog*, *Runs & Orchestrator*, *Decisions & Inbox*, *Doctor & Config*), plus a dedicated **"Workspaces & Orchestrators"** TreeView in the VS Code sidebar:
  - Clicking a workspace row in the **Workspaces Fleet** view opens its detail drawer (sessions, handoff prompt preview, message composer, reassign modal) **or** switches the active workspace context of the Backlog/Decisions/Runs views (`?workspace=<slug>&project=_workspace`).
  - Inside a single workspace, `ui-multi-project.md` (`All projects` vs `<project>`) remains completely unchanged as the second-level hierarchy (`Fleet (All Workspaces) -> Workspace (All Projects) -> Project`).

### 3.2 Fleet Control Plane Data Model (`GET /api/fleet` & `ai-orch workspace fleet --json`)

```json
{
  "ok": true,
  "generated_at": "2026-10-27T15:00:00Z",
  "broker": {
    "running": false,
    "pid": null,
    "port": null
  },
  "summary": {
    "registered_workspaces": 6,
    "unregistered_discovered": 7,
    "active_orchestrators": 2,
    "idle_or_stale_orchestrators": 1,
    "missing_orchestrators": 10,
    "live_interactive_sessions": 7,
    "open_questions_total": 0,
    "inbox_to_analyze_total": 3,
    "pending_verifications_total": 2,
    "orphan_project_configs": 4
  },
  "workspaces": [
    {
      "uuid": "52c62ed7-47c6-45e0-8136-6aa92350e4de",
      "slug": "ai-coding-tools",
      "title": "AI Coding Tools",
      "path": "/Users/Alfredo/works/ai-coding-tools",
      "registration_state": "registered",
      "projects_count": 5,
      "orchestrator": {
        "status": "active",
        "liveness_source": "transcript_mtime",
        "generation": 2,
        "tool": "claude",
        "model": "claude-opus-5-5",
        "kind": "interactive",
        "registry_session_id": "ai-coding-tools-d8",
        "provider_session_id": "5865a698-40a0-4f69-ad79-2e3ace4f7ffa",
        "display_name": "ai-coding-tools-d8",
        "transcript_exists": true,
        "last_seen": "2026-10-27T14:58:12Z",
        "turns": 0,
        "cursor": 0,
        "queue": {"queued": 0, "running": 0, "total": 0},
        "worker": {"alive": false, "pid": null}
      },
      "live_sessions": [
        {
          "display_name": "ai-coding-tools-d8",
          "provider_session_id": "5865a698-40a0-4f69-ad79-2e3ace4f7ffa",
          "tool": "claude",
          "kind": "interactive",
          "role": "orchestrator",
          "registered": true,
          "liveness": "active",
          "last_activity": "2026-10-27T14:58:12Z"
        },
        {
          "display_name": "ai-coding-tools-ea",
          "provider_session_id": "7b21c901-...",
          "tool": "claude",
          "kind": "interactive",
          "role": null,
          "registered": false,
          "liveness": "active",
          "last_activity": "2026-10-27T14:40:00Z"
        }
      ],
      "kpis": {
        "ready_queue_count": 1,
        "in_progress_count": 4,
        "inbox_to_analyze": 0,
        "open_questions": 0,
        "unapplied_answers": 0,
        "verify_by_this_workspace": 1,
        "delivered_awaiting_others": 2,
        "unread_mail": 0
      },
      "last_activity": "2026-10-27T14:58:12Z"
    }
  ],
  "orphan_configs": [
    {
      "name": "test_orchestrator_reassign_end0",
      "config_path": "/Users/Alfredo/.config/ai-orchestration/projects/test_orchestrator_reassign_end0/orchestration.toml",
      "reason": "no_matching_workspace_directory"
    }
  ]
}
```

### 3.3 ASCII Mockup of the Cross-Workspace Control Plane Panel

```text
+========================================================================================================================+
| AI ORCHESTRATION CONTROL PLANE   [0. Workspaces Fleet*] [1. Backlog] [2. Runs & Orch] [3. Decisions/Inbox] [4. Doctor] |
+------------------------------------------------------------------------------------------------------------------------+
| Fleet Summary: 6 Registered | 7 Unregistered | 2 Active Orch | 1 Stale Orch | 7 Live Sessions | 2 Verify Q | 4 Orphans |
| Filter: [All (13) v]  Search: [____________________]  [+ Scan Roots]  [Clean 4 Orphan Configs...]  [Refresh]           |
+========================================================================================================================+
| WORKSPACE (PROJECTS)      | ORCHESTRATOR HOLDER & LIVENESS        | LIVE SESSIONS / CONSOLES   | PIPELINE & QUEUES     |
+---------------------------+---------------------------------------+----------------------------+-----------------------+
| * ai-coding-tools (5)     | [ACTIVE] gen 2 · claude (interactive) | * ai-coding-tools-d8 (orch)| Ready: 1 | InProg: 4  |
|   ~/works/ai-coding-tools | id: 5865a698.. ("ai-coding-tools-d8") | o ai-coding-tools-ea (unreg| Q: 0 | Inbox: 0       |
|   [Registered]            | seen: 1m ago · Q: 0 · cursor: 0       |   [Bind Orch] [Reg Console]| Verify-for-us: 1 (T071|
|   Actions: [Open] [Message] [Handoff / Reassign...] [Pause]                                    | Last: 1m ago          |
+---------------------------+---------------------------------------+----------------------------+-----------------------+
| ! d4science_kb (1)        | [ACTIVE] gen 3 · claude (interactive) | * d4science-kb-3d (orch)   | Ready: 0 | InProg: 0  |
|   ~/works/d4science_kb    | id: 9063f48c.. ("d4science-kb-3d")    |   (provider: 9063f48c..)   | Q: 0 | Inbox: 0       |
|   [Unregistered! -> Reg]  | seen: 4m ago · (gen 2 phantom retired)|                            | Verify-for-us: 2 (T070|
|   Actions: [Register WS...] [Open] [Message] [Handoff / Reassign...]                           | Last: 4m ago          |
+---------------------------+---------------------------------------+----------------------------+-----------------------+
| ~ smartgears4-migration(1)| [STALE 5d] gen 1 · kilo (interactive) | (none live)                | Ready: 3 | InProg: 1  |
|   ~/works/smartgears4_mig | id: ses_e9d0d360.. · turns: 0         |                            | Q: 0 | Inbox: 1       |
|   [Registered]            | last seen: 2026-10-22 (5 days ago)    |                            | Verify-for-us: 0      |
|   Actions: [Open] [Take Over / Reassign...] [Start Headless Worker] [Retire Stale]             | Last: 2026-10-22      |
+---------------------------+---------------------------------------+----------------------------+-----------------------+
| o porting-liferay (5)     | [MISSING] no orchestrator registered  | o porting-liferay-6d (unreg| Ready: 4 | InProg: 2  |
|   ~/works/gcube/porting.. | default_orchestrator: claude          | o porting-liferay-56 (unreg| Q: 0 | Inbox: 2       |
|   [Registered]            |                                       |   [Bind 6d as Orch...]     | Verify-for-us: 0      |
|   Actions: [Bind porting-liferay-6d as Orch...] [Start Headless] [Open] [Message 6d]           | Last: 2h ago          |
+---------------------------+---------------------------------------+----------------------------+-----------------------+
| o dave-agent (1)          | [MISSING] no orchestrator registered  | o dave-agent-92 (unreg)    | Ready: 2 | InProg: 1  |
|   ~/works/dave_agent      | default_orchestrator: claude          |   [Bind 92 as Orch...]     | Q: 0 | Inbox: 0       |
|   [Registered]            |                                       |                            | Verify-for-us: 0      |
|   Actions: [Bind dave-agent-92 as Orch...] [Start Headless] [Open] [Message 92]                | Last: 25m ago         |
+---------------------------+---------------------------------------+----------------------------+-----------------------+
| o d4science-python-lib(11)| [MISSING] no orchestrator registered  | o d4science-python-lib-1b  | Ready: 5 | InProg: 1  |
|   ~/works/d4science-py... | default_orchestrator: claude          |   [Bind 1b as Orch...]     | Q: 0 | Inbox: 0       |
|   [Registered]            |                                       |                            | Verify-for-us: 0      |
|   Actions: [Bind 1b as Orch...] [Start Headless] [Open] [Message 1b]                           | Last: 18m ago         |
+---------------------------+---------------------------------------+----------------------------+-----------------------+
| . gcube_audit, d4science-keycloak, gcube_atlas, ricerca_auto, ansible (+6 discovered, unregistered, no live session)   |
|   Actions: [Register Selected...] [Hide / Ignore in Discovery]                                                         |
+========================================================================================================================+
| SELECTED WORKSPACE DRAWER: porting-liferay  ->  Action: [Bind Interactive Session / Reassign] or [Send Message]        |
| +--------------------------------------------------------------------------------------------------------------------+ |
| | Target: (x) Interactive Session: porting-liferay-6d (claude, provider_id: 3f8a...)  ( ) Headless Worker (claude)   | |
| | Handoff: [x] Generate on-disk handoff prompt (00-INDEX + 2 inbox notes + 4 ready tasks) -> gen 1 (1 bump, atomic)  | |
| | Message / Instructions (optional): [Please triage the 2 inbox notes and check the ready queue.___________________] | |
| | [Preview Plan & Config Diff]  [Apply & Bind Role (expect_hash: 9c4e...)]                                           | |
| +--------------------------------------------------------------------------------------------------------------------+ |
+========================================================================================================================+
```

---

## 4. Use Cases to Update and Add

### 4.1 Existing Use Cases to Update

1. **`UC028` — Owner manages the orchestrator role, queue, and succession handoff (headless & interactive)** *(update title & criteria)*:
   - **Actor:** Owner / Orchestrator Session.
   - **Changes:** Remove the headless-only restriction. Cover all 5 succession paths (`missing -> interactive`, `headless -> interactive`, `interactive -> interactive`, `interactive -> headless`, `headless -> headless`).
   - **New Acceptance Criteria:**
     - `ai-orch orchestrator reassign --kind interactive --provider-session-id <id> [--display-name <name>]` binds the role in **one** generation bump (`N -> N+1`), retires generation `N`, writes the real target path in `--dry-run` diff headers, and never creates a phantom headless session.
     - Re-registering the same `provider_session_id` with a new `--display-name` updates the session record in place without bumping `generation`.
     - Fenced-out previous holders receive a `ROLE LOST` / `fenced-out-orchestrator` notice on subsequent CLI/MCP calls.
2. **`UC030` — Operator registers a workspace and discovers nested project task trees** *(update criteria)*:
   - **Changes:** Pass `--config-dir` through to `find_project_config_path()` so isolated registrations never leak into `~/.config/ai-orchestration/projects/`; ignore macOS APFS `st_dev` changes when `inode` and `[workspace] uuid` match.

### 4.2 New Use Cases to Add

3. **`UC038` — Orchestrating session receives role feedback, claims a missing role, and handles fencing upon succession**:
   - **Actor:** Interactive or Headless Orchestrator Session.
   - **Acceptance Criteria Outline:**
     - Running a task-mutating command (`tasks new`, `tasks transition`) in a workspace with `orchestrator: missing` prints a one-line registration hint on stderr/MCP text (`T071`).
     - Running `ai-orch orchestrator status` and `ai-orch sessions role` returns identical liveness (`active`, `idle`, `stale`, `missing`) computed from heartbeat + provider transcript mtime.
     - When generation `N` is superseded by generation `N+1`, generation `N`'s next `ai-orch` call reports `ROLE LOST (superseded by gen N+1)`.
4. **`UC039` — Owner inspects the cross-workspace fleet panel and reassigns or binds an interactive orchestrator**:
   - **Actor:** Owner.
   - **Acceptance Criteria Outline:**
     - `ai-orch workspace fleet [--scan-root <dir>] --json` (and `GET /api/fleet`) returns all registered workspaces, discovered unregistered workspaces, orchestrator holder + liveness, live/recent provider sessions correlated by workspace `cwd`, and pipeline KPIs (`ready`, `inbox`, `open_questions`, `verify_by`).
     - From the fleet panel (or CLI), the owner binds a discovered unregistered interactive session (`porting-liferay-6d`) as generation `N+1` orchestrator with preview-then-apply (`plan_hash`).
5. **`UC040` — Owner or peer orchestrator sends a message to a workspace orchestrator or interactive console without permission laundering**:
   - **Actor:** Owner (via UI Panel) or Peer Orchestrator (via Broker MCP / CLI).
   - **Acceptance Criteria Outline:**
     - Owner message from the UI panel to a headless orchestrator enqueues an `owner_chat` turn; to an interactive console, deposits a message in its console mailbox (with optional `SendMessage` nudge).
     - Peer message from another workspace lands in metadata-only quarantine for a headless orchestrator until the owner clicks **Accept**, and is wrapped in `<untrusted_peer_mail nonce=...>` with `reduced_capability` policy so it can never execute shell commands or bypass per-session permissions.
6. **`UC041` — Operator audits and cleans up orphan project configs and stale registry entries (`workspace gc`)**:
   - **Actor:** Operator / Owner.
   - **Acceptance Criteria Outline:**
     - `ai-orch workspace gc` previews orphan directories in `~/.config/ai-orchestration/projects/` (such as `test_orchestrator_reassign_end0`, `test_ws`, `workspace`, `ws`) and stale SQLite entries with a `plan_hash`.
     - `ai-orch workspace gc --apply --expect-hash <hash>` moves orphan configs to `~/.config/ai-orchestration/.trash/<timestamp>/` and reconciles `registry.sqlite`.

---

## 5. Implementation Plan (Initiatives & Tasks, Absorbing T070, T071, T072, 16.7, 16.8)

We recommend structuring the implementation as **Initiative 17 (`17-orchestrator-control-plane`)** (or completing `16.7`/`16.8` in alignment with it), ordered so that foundational registry and identity fixes land first:

| Task ID | Title | Size | Depends on | Absorbs / Replaces | Repo(s) |
| --- | --- | --- | --- | --- | --- |
| **17.1** | **Session identity by `provider_session_id`, unified liveness (`compute_liveness`), and `config show` cwd default** — Key sessions by `provider_session_id` so display-name renames (`c1 -> d8`) update in place without bumping generation; unify `orchestrator status` and `sessions role` liveness using heartbeat + provider transcript mtime + PID check; default `config show --workspace` to `.` and show real target path in `reassign --dry-run` diff headers. | M | - | **Absorbs `T072`** (and the rename fix from `N071`) | `ai-orchestration/` |
| **17.2** | **First-class interactive & headless succession (`orchestrator reassign` / `claim`) and fencing enforcement** — Add `--kind interactive\|headless`, `--provider-session-id`, `--bind-current`, `--display-name` to `reassign` and `rotate`; never fabricate phantom UUIDs when `--no-handoff` is used; single generation bump; return handoff prompt to interactive caller; enforce `fencing_token` and `ROLE LOST` / missing-orchestrator notices on CLI commands and skills. | M | 17.1 | **Absorbs `T070` and `T071`**; updates `UC028`, adds `UC038` | `ai-orchestration/` |
| **17.3** | **Registry reconciliation, macOS APFS `st_dev` fix, test isolation guard, and `ai-orch workspace gc`** — Forward `--config-dir` into `find_project_config_path()`; auto-register workspace in `registry.sqlite` on `orchestrator start/reassign/claim`; fix `st_dev` false-stale check when `inode` + `uuid` match; recognize/migrate `.ai-orchestration/orchestration.toml`; add `workspace gc` preview-then-apply to move `test_orchestrator_reassign_end0`, `test_ws`, `workspace`, `ws` to `.trash/`. | M | 17.1 | Adds `UC041`, updates `UC030` | `ai-orchestration/` |
| **17.4** | **Fleet aggregation engine (`ai-orch workspace fleet`) & provider session discovery** — Implement `ai-orch workspace fleet [--scan-root ...] --json` combining registered workspaces, discovered unregistered workspaces, orchestrator holder + liveness, local provider session discovery (`~/.claude/projects/`, Kilo/Codex stores, `cwd` process probe), and workspace KPIs (`ready`, `inbox`, `questions`, `verification-queue`). Also fix `server.py` and `dashboard-panel.ts` so `orchestrator`/`sessions` endpoints use `state.workspace` instead of `state.project_root`. | M | 17.2, 17.3 | Adds `UC039` | `ai-orchestration/` + `ai-orchestration-ui/` + `vscode-ai-orchestration/` |
| **16.7** *(updated)* | **Orchestrator workers in broker, recovery, `orchestrator.ask` tickets, and role/fencing notices** — Existing 16.7 scope updated to respect `kind: interactive` holders (when a workspace's orchestrator is `kind: interactive`, `orchestrator.ask` queues for or notifies the interactive holder rather than spawning a competing headless process unless `interactive -> headless` handoff is requested). | L | 16.5, 17.2 | Refines **16.7** | `ai-orchestration/` + `ai-orchestration-ui/` |
| **16.8** *(updated)* | **Workspace & console mail, quarantine, and permission-laundering guards** — Existing 16.8 scope updated with the Option 5B provenance rules (owner panel message vs peer workspace mail quarantine, `<untrusted_peer_mail>` envelope for consoles, optional `SendMessage` nudge using `display_name`). | L | 16.7 | Refines **16.8**, adds `UC040` | `ai-orchestration/` + `ai-orchestration-ui/` + `vscode-ai-orchestration/` |
| **17.5** | **Cross-Workspace Fleet Control Plane UI (Web UI + VS Code Extension)** — Add the 5th top-level tab `Workspaces Fleet` (and VS Code sidebar TreeView) with workspace cards/table, live session badges, 1-click `Register`, `Bind as Orchestrator / Reassign` modal, `Handoff Prompt` viewer, `Clean Orphans` modal, and `Send Message` drawer. | L | 17.4, 16.8 | Completes `UC039`, `UC040` | `ai-orchestration-ui/` + `vscode-ai-orchestration/` |

---

## 6. Open Questions for the Owner (To Become `Q###` Items)

### Q-1 (Proposed `Q011`): Interactive vs Headless Orchestrator Coexistence per Workspace
- **Context:** `events-and-triggers.md` §0/§0a originally stated "the orchestrator is always headless", while in daily practice on 2026-10-27 the owner runs interactive Claude Code / Kilo sessions as the active orchestrators of `ai-coding-tools` and `d4science_kb` (`N068`, `N071`).
- **Options:**
  - **Option A (Either-Or Holder with Seamless Handoff — Recommended):** A workspace's `orchestrator` role is held at any given generation by *either* an `interactive` session *or* a `headless` worker session (`kind: interactive | headless`). While an `interactive` holder is `active`/`idle`, the background headless worker does not run competing turns; the owner (or session) can hand off `interactive -> headless` (when closing the window) or `headless -> interactive` (when opening a window to take over) in one click/command.
  - **Option B (Always-Headless Role + Interactive Primary Console):** The `orchestrator` role in `orchestrator.json` is strictly headless, and interactive sessions are only registered as `role: primary_console`.
- **Recommendation:** **Option A**. It matches how the owner actually works today (`d4science_kb`, `ai-coding-tools`), avoids paying double tokens for a headless session when an interactive orchestrator is already open, and still supports unattended headless orchestration whenever no interactive orchestrator holds the role.

### Q-2 (Proposed `Q012`): Automatic Discovery Scan Roots for Unregistered Workspaces
- **Context:** 7+ workspaces under `~/works/` (`d4science_kb`, `gcube_audit`, `d4science-keycloak`, `gcube_atlas`, `ricerca_auto`, `d4science-evolution-assurance`, `ansible`) have `tasks/` or `.ai-orchestration/` but are not in `registry.sqlite`.
- **Options:**
  - **Option A (Configurable Scan Roots with Depth-2 Auto-Discovery — Recommended):** Default `workspace_roots` to the parent directories of already-registered workspaces (e.g. `~/works`, `~/works/gcube`) configurable in global `orchestration.toml` (`[discovery] workspace_roots = [...]`). The Fleet panel lists discovered unregistered workspaces with an `Unregistered` badge and a 1-click `Register…` button (preview -> apply), plus an `Ignore` action.
  - **Option B (Manual Registration Only):** Only show workspaces explicitly added via `ai-orch workspace register`.
- **Recommendation:** **Option A**, because unregistered workspaces are the #1 reason the registries disagreed with reality on 2026-10-27.

### Q-3 (Proposed `Q013`): Local Provider Session Probing (`~/.claude/projects`, Process Table)
- **Context:** Interactive Claude Code sessions (`porting-liferay-6d`, `dave-agent-92`, etc.) do not appear in `.ai-orchestration/sessions/` until they run an `ai-orch` command.
- **Options:**
  - **Option A (Read-Only Provider Transcript & Process Probe — Recommended):** Allow `ai-orch workspace fleet` (and `sessions list --discover`) to read-only inspect `~/.claude/projects/<escaped-cwd>/*.jsonl` (mtime + session UUID/slug) and `ps`/`lsof` working directories for the current OS user to display live unregistered sessions in the Fleet panel and offer 1-click binding.
  - **Option B (Strictly Self-Registered Sessions):** Only show sessions that have explicitly called `ai-orch sessions register` or `whoami`.
- **Recommendation:** **Option A**, combined with piggybacked auto-registration when any session calls `ai-orch` or the broker MCP shim.

### Q-4 (Proposed `Q014`): Placement of the Cross-Workspace View in Web UI & VS Code
- **Context:** Where should the cross-workspace panel live relative to `ui-multi-project.md` (Project vs Common Workspace view) and `orchestration-extension-spec.md` (4 tabs)?
- **Options:**
  - **Option A (5th Top-Level Tab `Workspaces Fleet` + VS Code Sidebar TreeView — Recommended):** Add a dedicated top-level `Workspaces Fleet` tab in the dashboard (and a `Workspaces` TreeView in the VS Code sidebar) focused on orchestrators, live sessions, cross-workspace KPIs, messaging, and handoff; clicking a workspace switches the active workspace context for the other 4 tabs.
  - **Option B (3rd Level Inside the Existing Project Switcher Dropdown):** Add "All Workspaces" at the top of the project selector dropdown in the Backlog tab.
- **Recommendation:** **Option A**, because orchestrator management, session liveness, and cross-workspace messaging have a fundamentally different shape from a task backlog table.

### Q-5 (Proposed `Q015`): Delivery of Messages to Live Interactive Sessions
- **Context:** When the owner (from the Fleet panel) or another workspace sends a message to a workspace whose orchestrator (or target) is a live interactive session (e.g. Claude Code `d4science-kb-3d`):
- **Options:**
  - **Option A (Durable Mailbox + CLI/MCP Piggyback Notice + Opt-In Claude `SendMessage` Nudge — Recommended):** Always store the message durably in the workspace/console mailbox and surface a 1-line notice on the session's next `ai-orch` / MCP tool call; when both sender/relay and target are Claude Code and the owner enables `[mail] claude_sendmessage_nudge = true` (or clicks "Nudge Live Session" in the panel), also send a short `claude-mcp` cross-session `SendMessage` notification pointing to the mailbox message ID (never raw unvetted instructions).
  - **Option B (Pull-Only via Mailbox / MCP Notice, Never `SendMessage`):** Never invoke `claude -p` relay for `SendMessage` nudges; rely strictly on the target session calling `ai-orch` or the human pasting a prompt.
- **Recommendation:** **Option A** (with `SendMessage` nudge available on owner click in the panel and opt-in for peer mail), because an idle interactive Claude session waiting at the prompt will not call an MCP tool until nudged or spoken to by the owner.
