# Study: Cross-Workspace Orchestrator Control Plane, Feedback, Handoff & Registry Consistency (T073)

- **Status:** draft 2 — revised after independent Codex review (2026-10-27)
- **Task:** `T073 (Studio pannello orchestratori)`
- **Sources:** `N071`, `N068`, `N069`, `N070`
- **Related specs:** `ui-multi-project.md`, `orchestration-broker-mcp.md`, `orchestration-extension-spec.md`, `events-and-triggers.md`, `control-plane-safety.md`, `peer-messaging.md` (superseded)
- **Related use cases:** `UC028`, `UC030`, `UC033`, `UC034`, `UC037`
- **Related tasks & initiatives:** `T070` (done), `T072` (done), `T083` (same-provider-id rename), `T071` (open), `16.5` (bounced), `16.7` (open), `16.8` (open), `16.9` (done, with read-only all-workspaces overview gap), `17` (`17-use-cases-drive-tasks`, taken)
- **Pinned sibling-repo commits inspected:** `ai-orchestration-ui` at `3fe9d9e`, `vscode-ai-orchestration` at `dab76d0`

---

## Executive Summary & Core Recommendation (10-Line Synthesis)

1. **No Prompt Injection into Interactive Sessions, Ever:** Never send text, relay prompts, content-free `SendMessage` nudges, or auto-ingested handoff prompts into a live interactive session; messages and handoff records reach interactive sessions strictly via a **pull-only mailbox / pending-handoff record** read on the session's next turn, paired with a UI/OS notification to the human.
2. **Strict Authority Matrix & Human Proof (`Q-F`):** Only a self-identifying session may `claim` a `missing` role; only the current holder may initiate a voluntary `hand-off`; `stale` takeover requires the owner (or prior holder declaration); active `reassign` and registry `cleanup`/`unregister` require the owner (or current holder for reassign) — **never** an agent with `--force`. Because `~/.config/ai-orchestration/ui-token` is readable by local agents, owner-only actions require human-bound confirmation (an open design point).
3. **Provider-Scoped Identity `(tool, provider_session_id)`:** Treat `(tool, provider_session_id)` as the session identity when verified and non-colliding, and agent names (`ai-coding-tools-d8`) as mutable display labels (`T083` renames the record in place without a generation bump), with explicit rules for fork/resume, duplicate live clients, and missing IDs.
4. **Orthogonal Liveness Dimensions (`Q-D`, `Q-G`):** Separate `heartbeat_valid` (protocol authority), `recent_activity` (transcript mtime hint), `process_observed` (`ps`/`lsof` hint), and `takeover_eligible` (policy state); local file/process probes are **read-only display hints only** and never authorize automatic binding or takeover, nor does a stale interactive holder automatically fall back to a headless worker (`Q-A`).
5. **Truly Read-Only Status Invariant:** Fix `get_orchestrator_status()` (`scripts/orchestration_orchestrator.py:799-825`), which today acquires `orchestrator_lock` and mutates/migrates `orchestrator.json` via `_migrate_orchestrator_cursors()`, violating the read-only `status` invariant (`T026`).
6. **Transactional Succession with Rollback:** Fix the non-transactional defect in `reassign_orchestrator()` (`scripts/orchestration_orchestrator.py:2111-2148`, which writes `orchestration.toml` before `rotate_orchestrator()` and leaves mutated config behind when rotation fails) by enforcing CAS on `(expected_generation, expected_config_hash)` with full compensation/rollback on failure.
7. **Pending Handoff Acceptance for Interactive Targets:** Reassigning or handing off toward an interactive session writes a `pending_handoff` state (carrying the file-derived handoff bundle) that completes transition to `active` only when the target interactive session (prompted by its human operator) explicitly accepts/acknowledges it.
8. **Report-Only Registry Reconciliation & Safe Quarantine:** Keep `registry.sqlite` and `.ai-orchestration/orchestrator.json` reconciled via report-only diagnostics by default, explicit relink/unregister, and owner-confirmed reversible `.trash/` quarantine — never using filename patterns (`ws`, `test_*`) as deletion evidence or `/tmp` path heuristics instead of explicit `--config-dir` / `AI_ORCHESTRATION_CONFIG`.
9. **Fix Multi-Project Orchestrator Scoping:** Fix `ai-orchestration-ui/backend/server.py` (`3fe9d9e`) and `vscode-ai-orchestration/src/views/dashboard-panel.ts` (`dab76d0`) so `orchestrator` and `sessions` endpoints always bind to the workspace root (`state.workspace`), never to a child project (`state.project_root`).
10. **Sequenced Plan in Initiative 18 (Consuming T070, T072, T083):** Consume delivered `T070`/`T072` and `T083`, reconcile bounced `16.5` before `16.7`/`16.8`, classify the missing read-only all-workspaces overview as a `16.9` validation gap vs interactive fleet controls in **Initiative 18** (`18.1`–`18.8`), and resolve owner questions `Q-A`..`Q-G` first.

---

## 1. Problem and Empirical Evidence (Observed State on 2026-10-27)

On 2026-10-27, the owner observed that there is no single place to see which workspace has an orchestrator, whether that orchestrator is alive, which interactive sessions are running across workspaces, or how to hand off / reassign the orchestrator role cleanly. Inspecting the live machine state read-only reveals four mutually inconsistent views of reality.

### 1.1 Workspace Registry (`ai-orch workspace list --json`)

Running `./bin/ai-orch workspace list --json` (both under default `/usr/bin/python3` 3.9 and under `/opt/homebrew/bin/python3` 3.11+) returns 6 registered workspaces:

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

**Two defects uncovered in `list_workspaces` (`scripts/orchestration_registry.py:988-1005`):**
1. **`st_dev` change observed across a macOS reboot:** `ai-coding-tools` and `d4science-python-library` were registered on Oct 20–21 when `os.stat(cpath).st_dev` was `16777231`. Across a subsequent reboot on this machine, `st_dev` for the same APFS volume became `16777234`. Even though `canonical_path` exists, `st_ino` is unchanged (`329323713` and `412183655`), and `orchestration.toml`'s `[workspace] uuid` matches, `cur_st.st_dev != d["device"]` marks both workspaces `stale: true`.
2. **Python 3.9 `tomllib` silent exception:** When invoked in a shell where `/usr/bin/python3` (3.9) precedes `/opt/homebrew/bin/python3`, `tomllib` is `None`. `load_toml_file()` raises `RuntimeError`, which `list_workspaces()` catches with a bare `except Exception: stale = True`, reporting **all 6 workspaces** as `stale: true`.

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
- Four directories (`test_orchestrator_reassign_end0`, `test_ws`, `workspace`, `ws`) are **test leftovers** written into the user's real `~/.config/ai-orchestration/projects/` because:
  - `plan_workspace_register()` (`scripts/orchestration_registry.py:676`) and `plan_projects_discover()` (`line 1195`) call `find_project_config_path(canonical)` without forwarding `config_dir` (`--config-dir "$T/cfg"`), so probes and unit tests that pass `--config-dir` without setting `AI_ORCHESTRATION_CONFIG` write their `[workspace]` TOML into `~/.config/ai-orchestration/projects/<temp_dir_name>/orchestration.toml`.
  - `test_orchestrator_reassign_end0` was created by a pytest `tmp_path` test calling `orchestrator reassign` without isolating `AI_ORCHESTRATION_CONFIG`.

### 1.3 Per-Workspace Orchestrator Status, Sessions & Live Claude Code Sessions

Scanning all 20 folders under `~/works/*` and `~/works/gcube/*` that contain `tasks/` or `.ai-orchestration*` and comparing them with the 7 live Claude Code sessions reported by Claude's `ListAgents` (`ai-coding-tools-d8`, `ai-coding-tools-ea`, `porting-liferay-6d`, `porting-liferay-56`, `dave-agent-92`, `d4science-python-library-1b`, `d4science-kb-3d`):

| Workspace Path | In SQLite Registry? | `orchestrator status` | `sessions list` (active / total) | Live Claude Sessions (`ListAgents`) | Discrepancy Summary |
| --- | --- | --- | --- | --- | --- |
| `~/works/ai-coding-tools` | Yes (`stale: true` due to `st_dev`) | `active`, gen 2, `claude`, `session_id: ai-coding-tools-d8`, `provider_session_id: 5865a698-...` | 0 active, 1 `stale` (`ai-coding-tools-d8`, gen 2), 1 `retired` (`ai-coding-tools-c1`, gen 1) | `ai-coding-tools-d8` (orchestrator), `ai-coding-tools-ea` | `orchestrator status` says `active`, `sessions list` says `stale` (>300s since registration); `ai-coding-tools-ea` unknown; rename `c1 -> d8` forced gen 1 -> 2 |
| `~/works/d4science_kb` | **No** (only in `projects/d4science_kb`) | `active`, gen 3, `claude`, `session_id: f40e1f4e-...`, `provider_session_id: 9063f48c-...` | 0 active, 1 `stale` (gen 3 interactive), 2 `retired` (gen 2 phantom headless `f5f121da`, gen 1 kilo `ses_e9b...`) | `d4science-kb-3d` (orchestrator) | Unregistered in SQLite; `orchestrator status` says `active` while `sessions list` says `stale`; N068 created phantom headless gen 2 |
| `~/works/smartgears4_migration` | Yes (`active`) | `active`, gen 1, `kilo`, `session_id: cc1dd376-...`, `provider_session_id: ses_e9d0...` | 0 active, 1 `stale` (last seen `2026-10-22T10:22:24Z`, 5 days ago!) | None | `orchestrator status` claims `active` for a session untouched for 5 days (`orchestrator.json` static status) |
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

### 1.4 Concrete Friction Cases Observed on 2026-10-27

1. **Case N068 (`d4science_kb` phantom Claude headless session & double generation bump; addressed in `T070`):**
   - `d4science_kb` had a stale gen 1 interactive Kilo holder (`ses_e9bdf3ba5ffeyIjRCwCFIEeG4M`, last seen 2026-10-22, 0 turns).
   - When the session ran `ai-orch orchestrator reassign --tool claude --model claude-opus-5-5 --no-handoff --expect-hash <hash>`, `rotate_orchestrator()` (`scripts/orchestration_orchestrator.py:1862`) executed `cand_prov_id = str(uuid.uuid4()) if target_tool == "claude" else None` (a **Claude-only** pre-allocation meant for `claude -p --session-id <uuid>`). Because `--no-handoff` skipped invoking `claude -p`, generation 2 (`f5f121da`) recorded a fabricated `provider_session_id` (`a168b9a6-4ffd-4434-972d-2b4588434bfa`) with no transcript on disk.
   - Binding the real interactive session (`9063f48c-47d4-4079-8d84-bd8e25babd33`) required a second manual command (`sessions register --role orchestrator`), bumping to generation 3. (`T070`, now delivered and done, adds interactive binding to `reassign`).
2. **Case N069 (`config show` ignores cwd & `reassign --dry-run` hides target path; addressed in `T072`):**
   - `ai-orch config show` defaulted `--workspace` to `None`, printing `Project config: None (exists=False)` from inside `~/works/d4science_kb`, and `orchestrator reassign --dry-run` printed `--- a/orchestration.toml` instead of the real external path `~/.config/ai-orchestration/projects/d4science_kb/orchestration.toml`. (`T072`, now delivered and done, fixes both).
3. **Case N070 + Session Rename (`ai-coding-tools-c1` -> `ai-coding-tools-d8`; rename addressed in `T083`, registration hint in `T071`):**
   - The interactive Claude session orchestrating `ai-coding-tools` worked for days without registering because nothing in `AGENTS.md`, skills, or CLI output prompted it (`N070` / `T071`).
   - After an account switch, Claude Code renamed the live session from `ai-coding-tools-c1` to `ai-coding-tools-d8` while keeping the same `provider_session_id` (`5865a698-40a0-4f69-ad79-2e3ace4f7ffa`). Because `register_session()` checked `old_sess_id != reg_session_id` rather than matching `(tool, provider_session_id)`, re-registering bumped `generation` 1 -> 2 (`T083` now covers renaming the record in place when the same provider session ID re-registers with a new `--session-id`).

---

## 2. Existing Pieces and Gaps, Options, and Recommendations (Per Topic of N071)

### Topic 1: Orchestrator Feedback, Liveness Dimensions & Session Identity

#### Existing Pieces
- `<workspace>/.ai-orchestration/orchestrator.json`: stores `generation`, `cursor`, `delivery_cursor`, `trigger_scan_cursor`, `status`, and `current`.
- `<workspace>/.ai-orchestration/sessions/<session_id>.json`: stores session records; `compute_session_status()` marks a session `stale` when `now - last_seen > 300s` (`DEFAULT_STALE_TIMEOUT_SEC`).
- `T083`: updates `register_session` so re-registering with the same `provider_session_id` and a new `session_id` renames the session record in place without a generation bump.

#### Gaps
1. **Violation of the read-only `status` invariant in `get_orchestrator_status()`:**
   - Despite the docstring claiming `read-only, Spec §0, T026`, `get_orchestrator_status()` (`scripts/orchestration_orchestrator.py:799-825`) acquires `orchestrator_lock(ws)` and calls `_migrate_orchestrator_cursors(orch_doc, orch_file)`, which writes to `orchestrator.json` and deletes `.ai-orchestration/triggers/cursor.json` during a status read!
2. **Conflation of protocol liveness with display hints and takeover eligibility:**
   - `get_orchestrator_status()` reports static `orch_doc["status"]` (`"active"` even after 5 days in `smartgears4_migration`), while `sessions list` reports `"stale"` after 300 seconds because interactive sessions cannot emit background heartbeats while idle at the prompt.
   - Conflating "process exists or transcript was recently written" with "heartbeat valid" or "eligible for automatic takeover" is unsafe: a transcript mtime or `ps` match is an unverified local hint, not protocol authority.
3. **Provider-specific identity corner cases (`(tool, provider_session_id)`):**
   - **Collisions / Resume / Fork:** In Claude Code (`--resume <uuid>` or `--fork-session`), two client invocations over time (or accidentally in two terminals) can reference the same `provider_session_id`, or a forked session may share history before diverging.
   - **Duplicate live clients:** Two terminals running in the same workspace have distinct `provider_session_id`s; if both claim the same `provider_session_id`, the second must be rejected or flagged as a duplicate client conflict.
   - **Missing `provider_session_id`:** A headless Kilo/Codex session before its first turn, or an interactive session that registers without passing `--provider-session-id`, has `provider_session_id = null` and can only be identified by its `registry_session_id` until bound.
4. **Silent role loss / missing role (`T071`):**
   - Sessions running `ai-orch` commands or MCP tools receive no feedback in tool output when `orchestrator` is `missing` or when their generation was superseded (`fenced_out`).

#### Provider-Specific Identity & Liveness Rules

1. **Identity tuple `(tool, provider_session_id)`:**
   - `registry_session_id` is the internal primary key; `display_name` (e.g., `ai-coding-tools-d8`) is a mutable human label (`T083`).
   - **Same `(tool, provider_session_id)` re-registration (`T083`):** Updates `display_name`/`session_id` alias, `last_seen`, and `cwd` in place **without** bumping `generation`, provided `status` is not `retired`/`deregistered`.
   - **Retired `(tool, provider_session_id)`:** If a session whose `(tool, provider_session_id)` was explicitly `retired` (superseded by generation `N+1`) attempts to re-register as `orchestrator`, it must go through explicit succession (`claim`/`reassign`), never silently resurrecting generation `N`.
   - **Duplicate live client / fork:** If a caller supplies a `provider_session_id` already bound to a different `workspace` path, or if a `--fork-session` creates a new transcript UUID, it is treated as a distinct session; reusing the same `provider_session_id` concurrently from two different PIDs logs a `duplicate_client_warning`.
   - **Missing `provider_session_id`:** Allowed for initial registration (`provider_session_id: null`, state `unbound_provider_id`), but cannot use provider-id rename matching until bound.

2. **Four Orthogonal Liveness Dimensions (Replacing Single `active|stale` Conflation):**
   - `heartbeat_valid` (`bool` + `last_seen` age): `true` iff an explicit `sessions heartbeat` or authenticated CLI/MCP call from this `registry_session_id` occurred within `heartbeat_ttl` (default 300s). **Protocol fact.**
   - `recent_activity` (`timestamp | null`, hint): most recent mtime of the provider transcript file on disk (when opt-in provider store inspection `Q-C` is enabled). **Display hint only (`Q-D`).**
   - `process_observed` (`bool`, hint): whether an OS process for `tool` matching the session's `provider_session_id` or workspace `cwd` is currently visible in `ps`/`lsof`. **Display hint only (`Q-D`).**
   - `takeover_eligible` (`bool` + `reason`): policy state computed for succession (`true` when role is `missing`, holder explicitly declared `hand-off`/`stopped`, or holder has `heartbeat_valid == false` beyond the takeover threshold and owner initiates takeover; see `Q-G`).

#### Options & Trade-offs

- **Option 1A (Single Merged Status from Transcript Probe):** Compute a single `status = active` whenever a transcript file was modified within 15 minutes, and allow automatic takeover when it goes stale.
  - *Pros:* Simple UI badge.
  - *Cons:* Uses unauthenticated filesystem hints as protocol authority (`Q-D`), and risks automatic takeover of an idle interactive session while the human owner is reading code (`Q-A`).
- **Option 1B (Truly Read-Only Status + Four Orthogonal Liveness Dimensions + Piggybacked CLI/MCP Notices — Recommended):**
  1. Remove `orchestrator_lock` and `_migrate_orchestrator_cursors` from `get_orchestrator_status()` so `status` is 100% lock-free and read-only (`18.2`).
  2. Report both the **role state** (`missing` | `active` | `pending_handoff` | `rotating` | `paused` | `stopped`) and the **liveness breakdown** (`heartbeat_valid`, `recent_activity`, `process_observed`, `takeover_eligible`) identically in `orchestrator status` and `sessions role`.
  3. **No automatic fallback from a stale interactive holder (`Q-A`):** If an interactive holder's heartbeat expires (`heartbeat_valid: false`), it is displayed as `idle (heartbeat expired)` / `takeover_eligible`, **never** automatically replaced by a background headless worker without an explicit owner or holder action.
  4. Piggyback a 1-line notice on `ai-orch` CLI and broker MCP responses when `role == missing` (`T071`) or when the calling session's generation is `< current.generation` (`ROLE LOST / fenced-out`).

**Recommendation:** **Option 1B**.

---

### Topic 2: Transactional Handoff, Reassignment, Authority & No Prompt Injection

#### Existing Pieces
- `T070` (done): `orchestrator reassign` supports binding to an interactive session in one generation bump.
- `T072` (done): `config show` defaults `--workspace` to `.` and `reassign --dry-run` shows the real config path.
- `rotate_orchestrator()` (`scripts/orchestration_orchestrator.py:1803`) and `reassign_orchestrator()` (`line 1991`).

#### Gaps
1. **Non-transactional config write in `reassign_orchestrator()` (Current Code Defect):**
   - In `scripts/orchestration_orchestrator.py:2111-2148`, `reassign_orchestrator()` writes `routing.default_orchestrator` (and `model`) to `orchestration.toml` and emits `config.changed` **before** calling `rotate_orchestrator()` (`line 2133`).
   - If `rotate_orchestrator()` fails (e.g., handoff turn fails, tool binary missing, or CAS conflict), `reassign_orchestrator()` returns `{"ok": False, "status": "failed"}` (`line 2142`) **without rolling back `orchestration.toml`**! This leaves `orchestration.toml` pointing to the new tool while `orchestrator.json` stays on the old generation and old tool.
2. **Danger of prompt injection into interactive sessions:**
   - Any design that injects text into a live interactive session (via `claude -p` cross-session `SendMessage`, terminal stdin injection, or auto-executed handoff prompts) violates session boundaries and enables cross-session prompt injection / permission laundering.
3. **Lack of explicit authority rules and CAS preconditions per succession operation:**
   - `claim`, `hand-off`, `takeover`, and `reassign` have different actors and preconditions, which today are not separated.

#### Strict Rule: Zero Prompt Injection into Interactive Sessions

- **Never inject text into a live interactive session.** `ai-orch`, the broker, and the UI must **never** call `SendMessage`, write to a pty/stdin, or auto-run a prompt inside an interactive Claude, Kilo, or Codex session.
- **How messages reach an interactive session:** Only via a **pull-only mailbox** (`mail.inbox` / `mail.read` or `ai-orch mail inbox`) that the session reads on its own next turn (cued by a 1-line tool-output notice on its next MCP/CLI call), plus a **UI / OS desktop notification** to the human operator (`"New message / handoff waiting for <workspace> — paste or run '/orch-inbox' in your terminal"`).
- **How reassignment / handoff toward an interactive session works:**
  1. Initiating a handoff or reassignment toward an interactive session (`target_kind = "interactive"`) does **not** push a prompt into the target session.
  2. Instead, it writes a durable **`pending_handoff` record** in `orchestrator.json` (and `.ai-orchestration/orchestrator/handoffs/gen-<N+1>.md`) containing the file-derived handoff summary (`00-INDEX.md`, open/unapplied questions, active runs, pending queue), fences generation `N`, and notifies the human in the UI/OS.
  3. The target interactive session (when its human operator instructs it or accepts in the UI/CLI via `ai-orch orchestrator accept-handoff --expect-generation <N+1>`) reads the handoff file pull-style and transitions `pending_handoff -> active`.

#### Transactional Succession State Machine, CAS & Rollback

Every succession operation (`claim`, `hand-off`, `takeover`, `reassign`) executes under `orchestrator_lock(ws)` (and `config_lock(target_path)` when config changes) with explicit Compare-And-Swap (`expect_generation`, `expect_config_hash`, `expect_plan_hash`):

```text
          (claim: gen 0 -> 1)
missing ----------------------> active (gen 1)

active (gen N)
  ├── [headless target]  --> rotating (gen N -> N+1, pre-image saved)
  │                             ├── handoff turn OK  --> commit config + active (gen N+1), retire gen N
  │                             └── handoff turn ERR --> rollback config pre-image + restore active (gen N)
  └── [interactive target] -> pending_handoff (gen N -> N+1, gen N fenced, handoff bundle written)
                                ├── target accepts (`accept-handoff`) --> active (gen N+1), retire gen N
                                └── owner cancels / expires           --> rollback config pre-image + restore gen N (or stopped)
```

- **Fixing the `reassign_orchestrator` config-write defect (`scripts/orchestration_orchestrator.py:2111-2148`):**
  1. Record `config_preimage_bytes` and `orch_preimage_doc` before any mutation.
  2. Hold `config_lock` + `orchestrator_lock` to validate `expect_hash` and `expect_generation`, and write a staged transition record (`status = "rotating"` or `"pending_handoff"` with `rollback_config_preimage`).
  3. For headless rotation with handoff: run the candidate session's handoff turn **before** committing the final `orchestration.toml` change (or restore `config_preimage_bytes` atomically and emit `orchestrator.rotation_rolled_back` if the handoff turn fails).
  4. For Claude headless rotation with `--no-handoff`: do **not** fabricate a random `provider_session_id` before `claude -p` runs; set `provider_session_id: null` (`pending_first_turn`) until the first real turn creates the Claude transcript.

#### Options & Trade-offs

- **Option 2A (Immediate Promotion of Interactive Target + Push Nudge):** Immediately mark the target interactive session `active` on `reassign` and send it a `SendMessage` nudge with the handoff prompt.
  - *Pros:* One step fewer for the human when switching windows.
  - *Cons:* Violates the zero-prompt-injection rule; the target interactive session might be mid-turn on unrelated work or unattended, and `reassign` leaves mutated config on failure.
- **Option 2B (Transactional CAS Succession with Config Rollback + Pull-Only `pending_handoff` Acceptance for Interactive Targets — Recommended):**
  Implement the transactional state machine above with full config pre-image rollback on failure and pull-only `accept-handoff` for interactive targets (or immediate activation only when the interactive session itself is the caller running `orchestrator claim --bind-current` in its own turn).

**Recommendation:** **Option 2B**.

---

### Topic 3: Cross-Workspace Panel (State, Pull-Only Messaging, Actions & `16.9` Classification)

#### Existing Pieces
- `ui-multi-project.md` (16.9, delivered in `ai-orchestration-ui` `3fe9d9e` and `vscode-ai-orchestration` `dab76d0`): implements Project View and Common Workspace View for **one** bound workspace.
- `tasks/16-orchestration-broker/plan.md` line 40 (`16.9` Goal) and `orchestration-broker-mcp.md` §7b line 207: explicitly promised *"infine panoramica in sola lettura di tutti i workspace"* ("a third level, **all workspaces** (read-only overview: orchestrator status, unread mail, open questions per workspace)").

#### Classification: `16.9` Validation Defect vs New Scope (`T073` / Initiative 18)
- **What is a `16.9` validation gap (already in `16.9`'s stated Goal, but missing in `ai-orchestration-ui` `3fe9d9e` and `vscode-ai-orchestration` `dab76d0`):**
  1. The **read-only all-workspaces overview** (`orchestrator status`, `unread_mail`, `open_questions` per registered workspace) promised in `16.9` Goal (`plan.md:40`) was never built in `ai-orchestration-ui` or `vscode-ai-orchestration` (only `workspaces.list` MCP tool in `backend/broker/server.py:547` exists).
  2. **Scoping bug in `16.9` (`project_root` vs `workspace`):** In `ai-orchestration-ui/backend/server.py` (`3fe9d9e`, lines 4605, 5072–5430) and `vscode-ai-orchestration/src/views/dashboard-panel.ts` (`dab76d0`, lines 2474, 2901–3210), `sessions` and `orchestrator` endpoints pass `--workspace state.project_root(request)` instead of `state.workspace`. Selecting a child project in a multi-project workspace queries `<project>/.ai-orchestration/orchestrator.json` instead of `<workspace_root>/.ai-orchestration/orchestrator.json`.
- **What is genuinely new scope (from `N071` / `T073` -> Initiative 18):**
  1. **Interactive control-plane actions across workspaces:** claiming/reassigning/handing off orchestrators, accepting pending handoffs, registering/relinking/unregistering workspaces, and quarantining orphan project configs from the cross-workspace panel.
  2. **Richer per-workspace fleet state:** orthogonal liveness dimensions (`heartbeat_valid`, `recent_activity`, `process_observed`, `takeover_eligible`), registered + opt-in discovered sessions, ready-queue counts (`UC033`), inbox triage counts, and cross-workspace `verify-by` queues (`UC037`).
  3. **Opt-in candidate workspace suggestions** from configured scan roots (`Q-B`) and opt-in read-only provider session hints (`Q-C`, `Q-D`).

#### Options & Trade-offs (Workspace & Session Discovery in the Panel)

- **Option 3A (Implicit Auto-Scan of `~/works` and Implicit Session Binding):** Automatically scan `~/works` on startup and treat any discovered provider transcript as a live session eligible for binding.
  - *Pros:* Zero configuration on this machine.
  - *Cons:* Hardcodes directory assumptions, touches unconfigured trees, and confuses filesystem hints with registered state (`Q-B`, `Q-C`, `Q-D`).
- **Option 3B (Registered Workspaces by Default + Opt-In Configured Scan Roots as Suggestions Only + Read-Only Provider Hints — Recommended):**
  1. By default, the Fleet view queries **registered workspaces** from `registry.sqlite`.
  2. **Opt-in workspace scan roots (`Q-B`):** Only when the owner configures `[discovery] workspace_roots = [...]` (off by default) or explicitly clicks **"Scan Directory for Unregistered Workspaces…"** in the UI, scan those roots and display matches strictly as **suggestions** (`candidate_unregistered`) with a preview-then-apply `Register…` action.
  3. **Opt-in provider store hints (`Q-C`, `Q-D`):** If enabled by the owner, read-only inspect provider transcript stores (`~/.claude/projects/`, etc.) and `ps`/`lsof` to display `recent_activity` and `process_observed` hints in the UI. These hints **never** auto-register a session or authorize takeover.

**Recommendation:** **Option 3B**.

---

### Topic 4: Registry Consistency, Reconciliation and Safe Cleanup

#### Existing Pieces
- Global SQLite registry: `~/.config/ai-orchestration/broker/registry.sqlite` (`workspaces`, `projects`).
- Global per-project config store: `~/.config/ai-orchestration/projects/<folder-name>/orchestration.toml`.
- Workspace-local config: `<ws>/.ai-orchestration.local.toml`.
- Workspace-local runtime state: `<ws>/.ai-orchestration/orchestrator.json` and `<ws>/.ai-orchestration/sessions/*.json`.

#### Gaps
1. **Unforwarded `--config-dir` in `orchestration_registry.py` (`lines 676, 950, 995, 1037, 1195`):**
   - `plan_workspace_register()` and `plan_projects_discover()` call `find_project_config_path(canonical)` without passing `config_dir`. Any CLI call using `--config-dir <dir>` without setting `AI_ORCHESTRATION_CONFIG` writes project configs into the user's real `~/.config/ai-orchestration/projects/`.
2. **Discrepancies across `registry.sqlite`, `projects/*/orchestration.toml`, and `<ws>/.ai-orchestration/`:**
   - `d4science_kb` has `projects/d4science_kb/orchestration.toml` and `<ws>/.ai-orchestration/orchestrator.json`, but is missing from `registry.sqlite`.
   - `gcube_audit` has `<ws>/.ai-orchestration/orchestration.toml`, which `find_project_config_path()` ignores.
   - `ai-coding-tools` and `d4science-python-library` show `stale: true` in `registry.sqlite` because `st_dev` changed from `16777231` to `16777234` across a reboot on this machine.
3. **Unsafe cleanup heuristics:**
   - Deleting or quarantining configs based on filename patterns (`ws`, `workspace`, `test_*`) or path prefixes (`/tmp`, `/var/folders`) is unsafe: a user may legitimately name a folder `ws` or `workspace`, and test isolation must rely strictly on explicit `--config-dir` / `AI_ORCHESTRATION_CONFIG`, never path-prefix guessing.

#### Options & Trade-offs

- **Option 4A (Pattern-Based Auto-GC + `/tmp` Heuristics):** Automatically quarantine folders matching `test_*` or `ws` and skip registration when `cwd` is under `/tmp`.
  - *Pros:* Quick cleanup of the 4 current folders.
  - *Cons:* Fragile and dangerous; can quarantine a real user workspace named `ws` or break legitimate tests that test registration in temp dirs.
- **Option 4B (Report-Only Reconciliation, Explicit Relink/Unregister, and Owner-Confirmed Reversible Quarantine — Recommended):**
  1. **Isolation by explicit configuration only:** Fix `orchestration_registry.py` and `orchestration_orchestrator.py` so every function forwards `--config-dir` / `--global-config` / `AI_ORCHESTRATION_CONFIG` to `find_project_config_path()`. Fix offending tests to always set `AI_ORCHESTRATION_CONFIG` (or `--config-dir`). Never branch on `/tmp` or `/var/folders` path heuristics.
  2. **Handle `st_dev` change across reboot safely:** In `list_workspaces()` and `show_workspace()`, when `canonical_path` exists, `cur_st.st_ino == d["inode"]`, and the workspace config's `[workspace] uuid == d["uuid"]`, report `status: "active"` (with `device_changed: true` diagnostic) instead of `stale: true`, and allow `workspace reconcile` to update `device` in SQLite.
  3. **Four-tier registry maintenance (`ai-orch workspace reconcile`):**
     - **Report-only by default (`ai-orch workspace reconcile --json`):** Lists every discrepancy across `registry.sqlite`, `~/.config/ai-orchestration/projects/*/orchestration.toml`, and known workspace paths without modifying anything:
       - `unregistered_project_config`: config in `projects/<name>/orchestration.toml` whose `[workspace] uuid` is not in `registry.sqlite` (e.g., `d4science_kb`, `test_ws`, `workspace`, `ws`, `test_orchestrator_reassign_end0`), reporting whether a matching directory or `canonical_path` exists on disk.
       - `missing_canonical_path`: SQLite entry whose `canonical_path` no longer exists.
       - `device_shifted`: SQLite entry where `inode` + `uuid` match but `st_dev` changed across a reboot.
       - `legacy_dot_config`: `<ws>/.ai-orchestration/orchestration.toml` (as in `gcube_audit`).
     - **Explicit Relink (`ai-orch workspace relink <slug-or-uuid> <new-path> --apply --expect-hash <h>`):** Re-binds a moved workspace or updates `st_dev` after verification of `[workspace] uuid` and `inode`.
     - **Unregister-Only (`ai-orch workspace unregister <id> --apply --expect-hash <h>`):** Removes the row from `registry.sqlite` without deleting any files in the workspace or `projects/`.
     - **Reversible Quarantine (`ai-orch workspace quarantine-config <name>... --apply --expect-hash <h>`):** Only for specific project config entries **explicitly selected and confirmed by the owner** after inspecting the reconciliation report (never by filename pattern `ws`/`test_*`!). Moves `~/.config/ai-orchestration/projects/<name>` into `~/.config/ai-orchestration/.trash/<timestamp>/<name>` with a `manifest.json` so it can be restored in one command (`workspace restore-config`).

**Recommendation:** **Option 4B**.

---

### Topic 5: Authority Matrix, Owner Authentication & Permission Boundaries

#### Existing Pieces
- `events-and-triggers.md` §0c E3: unattended event-batch turns run with `policy = "reduced_capability"`.
- `orchestration-broker-mcp.md` §6: mail to an unattended orchestrator is quarantined (metadata-only) until the owner accepts it.
- `control-plane-safety.md` §2.3 (line 136): UI backend persists `~/.config/ai-orchestration/ui-token` (mode `0600`) and injects it into `<meta name="ai-orch-token">` for `/api/*` (`X-AI-Orch-Token`).

#### Gaps
1. **`ui-token` is NOT proof of a human owner action:**
   - Because `~/.config/ai-orchestration/ui-token` is a static file in the user's home directory (and also readable from `http://127.0.0.1:8780/index.html` by any process running as the same OS user), any local agent session with file-read or localhost-fetch capability can read `ui-token` and call `/api/orchestrator/reassign` or `/api/workspace/...`, impersonating the human owner!
2. **Undefined authority per lifecycle action:**
   - Today, any caller of the CLI can pass `--force` to `orchestrator start` or run `orchestrator reassign`, allowing an unprivileged agent session to overthrow an active orchestrator.

#### Normative Authority Matrix (`Q-F`)

| Action | Allowed Actor(s) | Preconditions & CAS | Explicitly Forbidden |
| --- | --- | --- | --- |
| **1. Claim missing role (`orchestrator claim`)** | Any self-identifying session (`(tool, provider_session_id)` or `registry_session_id`) running in the workspace, or Owner | `orchestrator.json` is `missing` or `stopped` (`expect_generation = 0` or current stopped gen) | Claiming when an `active`, `idle`, or `pending_handoff` holder exists |
| **2. Voluntary handoff (`orchestrator hand-off --to ...`)** | Current role holder (matching `current.registry_session_id` / `provider_session_id` + `fencing_token`), or Owner | `expect_generation == current.generation` | Any other agent session |
| **3. Stale takeover (`orchestrator takeover`)** | **Owner** (via authenticated control-plane action), or **holder-declared** (when the prior holder marked itself `draining`/`handing_off` or left an explicit takeover lease) | Current holder is `takeover_eligible == true` (`heartbeat_valid == false` past threshold) + `expect_generation == current.generation` | Autonomous takeover by a peer/console agent merely because `heartbeat_valid` expired (`Q-A`, `Q-F`) |
| **4. Active reassignment (`orchestrator reassign`)** | **Owner** (via authenticated control-plane action) or **Current Holder** (voluntary tool/session switch) | Preview diff + `expect_plan_hash` + `expect_generation`; if target is interactive, enters `pending_handoff` until target accepts | **NEVER** an non-holder agent session (remove/forbid agent `--force` takeover of an active role) |
| **5. Registry cleanup / quarantine / unregister** | **Owner only** (via authenticated control-plane action) | Explicit item list + `expect_plan_hash`; reversible move to `.trash/` | Any autonomous agent or background job |
| **6. Peer / Panel Messaging** | Owner or Peer Session (`mail.send`) | Headless recipient: metadata-only quarantine until Owner accepts. Interactive recipient: pull-only mailbox + UI/OS notification to human | Prompt injection, `SendMessage` into live interactive sessions, or auto-executing peer mail |

#### Distinguishing a Human Owner Action from a Local Agent Caller (Open Design Point `Q-F`)

Because agents and the UI backend run under the same macOS/Linux user account, a static file token (`~/.config/ai-orchestration/ui-token`) only protects against cross-origin browser attacks (CSRF/DNS rebinding), **not** against a local agent calling the CLI or HTTP API. To distinguish a real human owner confirmation from an agent caller, the control plane needs one of the following mechanisms (flagged as an open design point in `Q-F`):
1. **Option Auth-1 (OS-Native Confirmation Dialog via `osascript` / VS Code Extension Host Modal — Recommended for High-Impact Actions):**
   - In the **VS Code Extension**, the Extension Host runs in VS Code's privileged process and can require a native `vscode.window.showInformationMessage(..., { modal: true }, "Confirm")` click before invoking the broker/CLI with a short-lived single-use IPC secret held only in Extension Host memory.
   - In the **Web UI / Broker**, for owner-only actions (`reassign` active holder, `takeover`, `accept` peer mail body for unattended execution, `quarantine-config`), the broker can trigger a native macOS/Linux confirmation prompt (`osascript -e 'display dialog ...'` on macOS) or require a short human confirmation code displayed only in the native OS notification / VS Code status bar (unreachable via DOM/file reads by a CLI agent).
2. **Option Auth-2 (In-Memory WebSocket Session Nonce + Disallow CLI/MCP Execution of Owner-Only Actions):**
   - Owner-only mutations are disabled in the MCP tool surface (already true in `orchestration-broker-mcp.md` §3b line 147) and require a `confirm_token` issued over an established interactive browser/webview WebSocket session where the user clicked "Preview", paired with disallowing `curl`/headless fetches in agent tool allowlists. *(Caveat: an unrestricted `bash` agent could still open a WebSocket unless combined with Option Auth-1).*

---

## 3. Where the Panel Lives, Data Model & ASCII Mockup

### 3.1 Architectural Placement: Where Does the Panel Live?

- **Option P1 (Extend the Workspace Switcher Dropdown in `ui-multi-project.md`):** Add "All Workspaces" above "All Projects" inside the Task Backlog tab.
  - *Cons:* Task-centric columns do not fit orchestrator holder state, liveness dimensions, pending handoffs, registry reconciliation reports, or pull-mailbox management.
- **Option P2 (New 5th Top-Level Macro-View `Workspaces Fleet` + VS Code Sidebar TreeView — Recommended):**
  - Remediate the `16.9` validation gap by adding the read-only cross-workspace overview (`18.7`), and extend it in `18.8` with owner-confirmed control-plane actions in a dedicated top-level tab **`0. Workspaces Fleet`** (plus a **`Workspaces & Orchestrators`** VS Code sidebar TreeView).
  - Fix `ai-orchestration-ui/backend/server.py` (`3fe9d9e`) and `vscode-ai-orchestration/src/views/dashboard-panel.ts` (`dab76d0`) so all `/api/orchestrator/*` and `/api/sessions/*` calls use `state.workspace` (the workspace root) rather than `state.project_root(request)`.

### 3.2 Fleet Control Plane Data Model (`GET /api/fleet` & `ai-orch workspace fleet --json`)

```json
{
  "ok": true,
  "generated_at": "2026-10-27T16:15:00Z",
  "broker": {
    "running": false,
    "pid": null,
    "port": null
  },
  "summary": {
    "registered_workspaces": 6,
    "candidate_unregistered_workspaces": 0,
    "active_orchestrators": 2,
    "pending_handoffs": 0,
    "takeover_eligible_orchestrators": 1,
    "missing_orchestrators": 3,
    "reconciliation_issues": 7
  },
  "workspaces": [
    {
      "uuid": "52c62ed7-47c6-45e0-8136-6aa92350e4de",
      "slug": "ai-coding-tools",
      "title": "AI Coding Tools",
      "path": "/Users/Alfredo/works/ai-coding-tools",
      "registration_state": "registered",
      "reconciliation": {
        "status": "device_shifted",
        "inode_matches": true,
        "uuid_matches": true
      },
      "projects_count": 5,
      "orchestrator": {
        "role_state": "active",
        "generation": 2,
        "tool": "claude",
        "model": null,
        "kind": "interactive",
        "registry_session_id": "ai-coding-tools-d8",
        "provider_session_id": "5865a698-40a0-4f69-ad79-2e3ace4f7ffa",
        "display_name": "ai-coding-tools-d8",
        "liveness": {
          "heartbeat_valid": false,
          "last_seen": "2026-10-27T14:46:29Z",
          "recent_activity": "2026-10-27T16:10:00Z",
          "process_observed": true,
          "takeover_eligible": false,
          "takeover_reason": "interactive_holder_process_observed_no_auto_fallback"
        },
        "turns": 0,
        "cursor": 0,
        "queue": {"queued": 0, "running": 0, "total": 0},
        "pending_handoff": null
      },
      "sessions": [
        {
          "registry_session_id": "ai-coding-tools-d8",
          "display_name": "ai-coding-tools-d8",
          "provider_session_id": "5865a698-40a0-4f69-ad79-2e3ace4f7ffa",
          "tool": "claude",
          "kind": "interactive",
          "role": "orchestrator",
          "source": "registered",
          "liveness": {
            "heartbeat_valid": false,
            "recent_activity": "2026-10-27T16:10:00Z",
            "process_observed": true
          }
        }
      ],
      "discovered_session_hints": [
        {
          "display_name_hint": "ai-coding-tools-ea",
          "provider_session_id": "7b21c901-...",
          "tool": "claude",
          "source": "provider_store_hint",
          "recent_activity": "2026-10-27T15:40:00Z",
          "process_observed": true,
          "authority": "hint_only"
        }
      ],
      "kpis": {
        "ready_queue_count": 1,
        "in_progress_count": 4,
        "inbox_to_analyze": 0,
        "open_questions": 0,
        "unapplied_answers": 0,
        "verify_by_this_workspace": 1,
        "unread_mail": 0
      }
    }
  ],
  "reconciliation_report": [
    {
      "kind": "unregistered_project_config",
      "config_dir_name": "d4science_kb",
      "config_path": "/Users/Alfredo/.config/ai-orchestration/projects/d4science_kb/orchestration.toml",
      "matching_workspace_path": "/Users/Alfredo/works/d4science_kb",
      "has_orchestrator_json": true,
      "suggested_action": "register_or_relink"
    },
    {
      "kind": "unregistered_project_config",
      "config_dir_name": "test_orchestrator_reassign_end0",
      "config_path": "/Users/Alfredo/.config/ai-orchestration/projects/test_orchestrator_reassign_end0/orchestration.toml",
      "matching_workspace_path": null,
      "has_orchestrator_json": false,
      "suggested_action": "owner_review_for_quarantine"
    }
  ]
}
```

### 3.3 ASCII Mockup of the Cross-Workspace Control Plane Panel

```text
+========================================================================================================================+
| AI ORCHESTRATION CONTROL PLANE   [0. Workspaces Fleet*] [1. Backlog] [2. Runs & Orch] [3. Decisions/Inbox] [4. Doctor] |
+------------------------------------------------------------------------------------------------------------------------+
| Fleet: 6 Registered | 2 Active Holders | 1 Takeover-Eligible | 3 Missing Orch | 7 Reconciliation Findings              |
| Filter: [Registered (6) v]  [Reconciliation Report (7)...]  [Scan Configured Roots (Off)...]  [Refresh]                |
+========================================================================================================================+
| WORKSPACE (PROJECTS)      | ORCHESTRATOR ROLE & LIVENESS SIGNALS  | SESSIONS & HINTS (READ-ONLY)| PIPELINE & MAIL      |
+---------------------------+---------------------------------------+-----------------------------+----------------------+
| * ai-coding-tools (5)     | [ACTIVE] gen 2 · claude (interactive) | [Reg] ai-coding-tools-d8    | Ready: 1 | InProg: 4 |
|   ~/works/ai-coding-tools | id: 5865a698.. ("ai-coding-tools-d8") | [Hint] ai-coding-tools-ea   | Q: 0 | Inbox: 0      |
|   [Reg · dev-id shifted]  | HB: expired · Act: 1m · Proc: yes     |   (transcript hint only)    | Verify-for-us: 1     |
|   Owner Actions: [Open] [Deposit Mail to Mailbox] [Request Handoff / Reassign...]               | Unread Mail: 0       |
+---------------------------+---------------------------------------+-----------------------------+----------------------+
| ! d4science_kb (unreg)    | [ACTIVE] gen 3 · claude (interactive) | [Reg] f40e1f4e ("kb-3d")    | Ready: 0 | InProg: 0 |
|   ~/works/d4science_kb    | id: 9063f48c.. · (gen 2 retired)      |   provider: 9063f48c..      | Q: 0 | Inbox: 0      |
|   [Unregistered Config!]  | HB: expired · Act: 4m · Proc: yes     |                             | Verify-for-us: 2     |
|   Owner Actions: [Register & Relink...] [Open] [Deposit Mail to Mailbox] [Request Handoff...]   | Unread Mail: 0       |
+---------------------------+---------------------------------------+-----------------------------+----------------------+
| ~ smartgears4-migration(1)| [TAKEOVER ELIGIBLE] gen 1 · kilo (int)| [Reg] cc1dd376 (ses_e9d0..) | Ready: 3 | InProg: 1 |
|   ~/works/smartgears4_mig | HB: expired (5d) · Act: 5d · Proc: no |   (no live process)         | Q: 0 | Inbox: 1      |
|   [Registered]            | No auto-fallback (waits for owner)    |                             | Verify-for-us: 0     |
|   Owner Actions: [Open] [Owner Takeover / Reassign...] [Start Headless Worker]                  | Unread Mail: 0       |
+---------------------------+---------------------------------------+-----------------------------+----------------------+
| o porting-liferay (5)     | [MISSING] no orchestrator registered  | [Hint] porting-liferay-6d   | Ready: 4 | InProg: 2 |
|   ~/works/gcube/porting.. | default_orchestrator: claude          | [Hint] porting-liferay-56   | Q: 0 | Inbox: 2      |
|   [Registered]            |                                       |   (hints; claim from CLI)   | Verify-for-us: 0     |
|   Owner Actions: [Prepare Pending Handoff for 6d...] [Start Headless] [Open] [Deposit Mail]     | Unread Mail: 0       |
+========================================================================================================================+
| SELECTED WORKSPACE DRAWER: porting-liferay  ->  Owner Action: [Prepare Pending Handoff / Reassign]                     |
| +--------------------------------------------------------------------------------------------------------------------+ |
| | Target Kind: (x) Interactive Session (creates pull-only pending_handoff; target human/session must accept)         | |
| |              ( ) Headless Worker (runs transactional handoff turn; rolls back config if bootstrap fails)           | |
| | Target Tool / Provider ID: [claude v]  Provider Session ID: [3f8a-... (porting-liferay-6d)]                        | |
| | Preconditions (CAS): expect_generation=0, expect_config_hash=a81f...                                               | |
| | Delivery: Writes .ai-orchestration/orchestrator/handoffs/gen-001.md + OS/UI notification (NO prompt injection).    | |
| | [Preview Plan & Config Diff]  [Owner Confirm & Write Pending Handoff (expect_hash: 9c4e...)]                       | |
| +--------------------------------------------------------------------------------------------------------------------+ |
+========================================================================================================================+
```

---

## 4. Use Cases to Update and Add

### 4.1 Existing Use Cases to Update

1. **`UC028` — Owner manages the orchestrator role, queue, and transactional succession handoff (headless & interactive)** *(update title & criteria)*:
   - **Actor:** Owner / Current Holder Session.
   - **Changes:** Extend beyond headless-only succession to cover transactional CAS (`expect_generation`, `expect_hash`) across `claim`, `hand-off`, `takeover`, and `reassign`, with automatic rollback of `orchestration.toml` if rotation/bootstrap fails, and pull-only `pending_handoff -> accept-handoff` for interactive targets.
2. **`UC030` — Operator registers a workspace and discovers nested project task trees** *(update criteria)*:
   - **Changes:** Ensure `--config-dir` is forwarded to `find_project_config_path()` so isolated runs never write to `~/.config/ai-orchestration/projects/`; do not mark workspaces `stale` when `st_dev` changes across a reboot if `canonical_path`, `inode`, and `[workspace] uuid` match.

### 4.2 New Use Cases to Add

3. **`UC038` — Session claims a missing role, renames display id in place (`T083`), and receives pull-only fencing/role notices**:
   - **Actor:** Orchestrator / Console Session.
   - **Acceptance Criteria Outline:**
     - `ai-orch orchestrator status` is strictly lock-free and read-only (`18.2`) and returns the four orthogonal liveness fields (`heartbeat_valid`, `recent_activity`, `process_observed`, `takeover_eligible`).
     - Re-registering the same `(tool, provider_session_id)` with a new `--session-id` updates the record in place without bumping `generation` (`T083`).
     - Task-mutating commands in a workspace with `role_state == missing` emit a 1-line registration hint (`T071`); calls from a superseded generation emit a `ROLE LOST / fenced-out-orchestrator` notice and refuse orchestrator-only mutations.
4. **`UC039` — Owner views the cross-workspace fleet panel and performs transactional reassignment or pending handoff**:
   - **Actor:** Owner.
   - **Acceptance Criteria Outline:**
     - `ai-orch workspace fleet --json` (and `GET /api/fleet`) returns all registered workspaces (plus opt-in configured scan-root suggestions), orchestrator role state, orthogonal liveness signals, and pipeline KPIs (`ready`, `inbox`, `open_questions`, `verify_by`, `unread_mail`).
     - Reassigning toward an interactive session writes a `pending_handoff` record without injecting any prompt into the live session; the target session transitions the role to `active` via `ai-orch orchestrator accept-handoff`.
     - If a headless reassignment fails during bootstrap, `orchestration.toml` is rolled back to its pre-image.
5. **`UC040` — Owner or peer workspace sends a pull-only message without prompt injection or permission laundering**:
   - **Actor:** Owner (via UI Panel) or Peer Orchestrator (via Broker MCP / CLI).
   - **Acceptance Criteria Outline:**
     - Messages to an interactive session are stored in its pull-only mailbox and surfaced via UI/OS notification to the human and a 1-line notice on the session's next CLI/MCP call — **never** pushed via `SendMessage` or stdin injection.
     - Peer messages to a headless orchestrator remain quarantined (metadata-only) until owner acceptance and run under `reduced_capability`.
6. **`UC041` — Owner reconciles registry discrepancies and reversibly quarantines selected orphan project configs**:
   - **Actor:** Owner.
   - **Acceptance Criteria Outline:**
     - `ai-orch workspace reconcile --json` is 100% read-only and reports `unregistered_project_config`, `missing_canonical_path`, `device_shifted`, and `legacy_dot_config` without using filename heuristics.
     - Owner-selected orphan configs are moved to `~/.config/ai-orchestration/.trash/<timestamp>/` via `workspace quarantine-config <name>... --apply --expect-hash <hash>` and can be restored via `workspace restore-config`.

---

## 5. Implementation Plan (Initiative 18 & Integration with Initiative 16, T070, T071, T072, T083)

### 5.1 Integration Rules with In-Flight and Completed Work
- **Do not absorb completed tasks:**
  - `T070` (*orchestrator reassign lega il ruolo a una sessione interattiva esistente*) and `T072` (*config show usa la cartella corrente; l'anteprima di reassign mostra il percorso reale*) are **delivered and done**: Initiative 18 consumes their implementation as its baseline.
  - `T083` (*same provider id with a new session-id renames the record*) covers the `ai-coding-tools-c1 -> ai-coding-tools-d8` rename case: consumed by `18.3`.
  - `T071` (*sessions invited to register as orchestrator*) is open and is completed in `18.4`.
- **Initiative 16 alignment:**
  - `16.5` (*Broker MCP tools*) is currently `bounced` and must be reconciled (`T045`) before `16.7` (*Orchestrator workers in broker*) and `16.8` (*Workspace & console mail*).
  - `16.8` owns the mailbox storage, quarantine, and pull-only delivery mechanics (`UC040`).
  - `16.9` (*Project and common workspace views*) is marked `done`, but its Goal (`tasks/16-orchestration-broker/plan.md:40`) included the read-only all-workspaces overview and introduced the `state.project_root(request)` scoping bug on `/api/orchestrator/*` and `/api/sessions/*` in `ai-orchestration-ui` (`3fe9d9e`) and `vscode-ai-orchestration` (`dab76d0`). Task `18.7` remedies that `16.9` validation gap; `18.8` adds the new interactive control-plane actions.
- **Initiative numbering:** Initiative `17` (`17-use-cases-drive-tasks`) is already taken in `tasks/00-INDEX.md`. This plan uses **Initiative 18 (`18-orchestrator-control-plane`)**, split into one-commit tasks in strict dependency order:

### 5.2 Ordered One-Commit Tasks for Initiative 18 (`18-orchestrator-control-plane`)

| Task ID | Title (One Task = One Commit) | Size | Depends on | Relation to Existing Tasks | Repo(s) |
| --- | --- | --- | --- | --- | --- |
| **18.1** | **Record owner decisions (`Q-A`..`Q-G`) and authority/confirmation contract in spec** — Lock the authority matrix (`claim`, `hand-off`, `takeover`, `reassign`, `quarantine`), the human-owner confirmation mechanism beyond static `ui-token`, and the zero-prompt-injection rule in `orchestrator-control-plane-study.md` / `events-and-triggers.md`. | S | `Q-A`..`Q-G` | Gate before code changes | `ai-orchestration/` |
| **18.2** | **Strictly read-only `orchestrator status` invariant** — Remove `orchestrator_lock` acquisition and `_migrate_orchestrator_cursors()` file writes from `get_orchestrator_status()` (`scripts/orchestration_orchestrator.py:799-825`); move cursor migration strictly into mutating commands (`start`, `enqueue`, `run-next`, `rotate`, `reassign`). | S | 18.1 | Fixes read-only status defect (`T026` follow-up) | `ai-orchestration/` |
| **18.3** | **Provider-scoped session identity rules `(tool, provider_session_id)`** — Build on `T083` (in-place rename for same `provider_session_id`): enforce retired-session resurrection refusal, cross-workspace collision refusal, duplicate live PID warning, and `provider_session_id: null` (`pending_first_turn`) on Claude `--no-handoff` rotation (`scripts/orchestration_orchestrator.py:1862`). | M | 18.2, T083 | Consumes **T083** | `ai-orchestration/` |
| **18.4** | **Transactional succession (`claim`, `hand-off`, `takeover`, `reassign`) with config rollback and pull-only `pending_handoff`** — Build on delivered `T070` and `T072`: save and restore `orchestration.toml` pre-image if `rotate_orchestrator()` fails (`scripts/orchestration_orchestrator.py:2111-2148`); add `pending_handoff -> accept-handoff` for interactive targets; enforce authority checks (forbid agent `--force` takeover of active holder) and piggyback missing-role (`T071`) / `fenced-out` notices. | M | 18.3, T070, T072 | Consumes **T070**, **T072**; completes **T071**; updates `UC028`, adds `UC038` | `ai-orchestration/` |
| **18.5** | **Orthogonal liveness signals (`heartbeat_valid`, `recent_activity`, `process_observed`, `takeover_eligible`) as read-only hints** — Implement `compute_liveness_signals()` in `orchestration_sessions.py` and surface identical liveness objects in `orchestrator status` and `sessions role`; implement opt-in read-only provider transcript mtime and `ps`/`lsof` adapters strictly as display hints (never takeover/binding authority, no auto-fallback from stale interactive holder). | M | 18.4 | Implements `Q-A`, `Q-C`, `Q-D`, `Q-G` | `ai-orchestration/` |
| **18.6** | **Registry reconciliation (`workspace reconcile`), explicit config-dir forwarding, and reversible quarantine** — Forward `--config-dir` to `find_project_config_path()` in `orchestration_registry.py`; handle reboot `st_dev` shift (`device_shifted`) without false `stale: true`; add read-only `workspace reconcile`, `workspace relink`, and owner-confirmed `workspace quarantine-config` / `restore-config` (`.trash/`). | M | 18.2 | Updates `UC030`, adds `UC041` | `ai-orchestration/` |
| **18.7** | **Fleet read-only aggregation (`workspace fleet`) & `16.9` multi-project orchestrator scoping fix** — Fix `ai-orchestration-ui/backend/server.py` (`3fe9d9e`) and `vscode-ai-orchestration/src/views/dashboard-panel.ts` (`dab76d0`) to pass `state.workspace` instead of `state.project_root` to `orchestrator`/`sessions`; implement `ai-orch workspace fleet --json`, `GET /api/fleet`, and the read-only `Workspaces Fleet` overview promised in `16.9`. | M | 18.5, 18.6 | Remedies **16.9** validation gap; adds read-only half of `UC039` | `ai-orchestration/` + `ai-orchestration-ui/` + `vscode-ai-orchestration/` |
| **18.8** | **Interactive Fleet control-plane actions in Web UI & VS Code** — Add owner-confirmed UI actions in the `Workspaces Fleet` tab and VS Code TreeView: `Prepare Pending Handoff / Reassign` modal, `Accept Handoff` banner, `Register / Relink Workspace`, `Reconciliation & Quarantine` modal, and pull-only `Deposit Mail` composer (integrated with `16.8`). | M | 18.7, 16.8 | Completes `UC039`, `UC040` | `ai-orchestration-ui/` + `vscode-ai-orchestration/` |

---

## 6. Open Questions for the Owner (`Q-A`..`Q-G`)

*(Labels `Q-A`..`Q-G` are temporary study handles; the architect will assign canonical `Q###` IDs in `tasks/questions/`.)*

### Q-A: Interactive vs Headless Orchestrator Coexistence & Stale Interactive Holder Policy
- **Context:** `events-and-triggers.md` §0/§0a stated "the orchestrator is always headless", whereas on 2026-10-27 the owner actively uses interactive Claude Code / Kilo sessions as workspace orchestrators (`ai-coding-tools`, `d4science_kb`). Furthermore, interactive sessions cannot emit background heartbeats while idle waiting for the user.
- **Options:**
  - **Option A (Either-Or Holder + No Automatic Fallback from Stale Interactive Holder — Recommended):** A workspace's `orchestrator` role is held at any generation by either an `interactive` session or a `headless` worker (`kind: interactive | headless`). If an `interactive` holder's heartbeat expires (`heartbeat_valid: false`), it becomes `takeover_eligible` in the UI, but a background headless worker **never** automatically takes over or runs competing turns unless the current holder explicitly hands off (`interactive -> headless`) or the owner explicitly triggers takeover/reassignment.
  - **Option B (Auto-Fallback to Headless After Timeout):** Automatically rotate an idle interactive holder to a headless worker after `N` minutes without a heartbeat.
  - **Option C (Strictly Headless Role Only):** Interactive sessions may only register as `role: console`, never `role: orchestrator`.
- **Recommendation:** **Option A**. It respects the owner's interactive workflow and prevents a background headless worker from hijacking the role while the owner is simply pausing between interactive turns.

### Q-B: Unregistered Workspace Discovery Scan Roots
- **Context:** 7+ folders under `~/works/` have `tasks/` or `.ai-orchestration/` but are not registered in `registry.sqlite`.
- **Options:**
  - **Option A (Explicit Configured Scan Roots, Off by Default, Suggestions Only — Recommended):** Do not scan arbitrary directories by default. Provide an opt-in setting `[discovery] workspace_roots = [...]` in global `orchestration.toml` (and an explicit **"Scan Directory…"** button in the UI). Discovered folders are shown strictly as read-only **suggestions** (`candidate_unregistered`) that nothing acts on until the owner previews and applies `workspace register`.
  - **Option B (Always-On Auto-Scan of Parent Directories):** Automatically scan parent folders of registered workspaces on every `workspace fleet` call.
  - **Option C (No Directory Scanning):** Only ever show workspaces already in `registry.sqlite`.
- **Recommendation:** **Option A**. It avoids unrequested filesystem walks while giving the owner a 1-click way to discover and register existing workspaces when desired.

### Q-C: Inspecting Local Provider Stores (`~/.claude/projects`, Kilo/Codex Stores, `ps`/`lsof`)
- **Context:** Live interactive sessions (`porting-liferay-6d`, `dave-agent-92`, etc.) do not appear in `.ai-orchestration/sessions/` until they run an `ai-orch` command.
- **Options:**
  - **Option A (Opt-In Read-Only Inspection of Provider Stores & Process Table — Recommended):** Allow `ai-orch workspace fleet` (when enabled in config or requested in the UI) to read-only inspect local provider metadata (`~/.claude/projects/<escaped-cwd>/*.jsonl` mtimes/UUIDs, Kilo/Codex session stores) and current-user `ps`/`lsof` working directories to list unregistered session hints in the Fleet panel.
  - **Option B (Never Inspect Provider Stores or Process Table):** Only show sessions that have explicitly called `ai-orch sessions register` or `ai-orch mcp`.
- **Recommendation:** **Option A** (strictly read-only and scoped to known workspace paths).

### Q-D: Authority of Provider Store & Process Discoveries over Liveness and Takeover
- **Context:** If `Q-C` (inspecting transcript mtimes and `ps`/`lsof`) is enabled, should those signals ever automatically bind a role, extend a protocol lease, or trigger/block a takeover?
- **Options:**
  - **Option A (Read-Only Display Hints Only, Zero Protocol Authority — Recommended):** Transcript mtime (`recent_activity`) and process observation (`process_observed`) are displayed in the UI as **informational hints only** (`authority: "hint_only"`). They never auto-register a session, never auto-bind an orchestrator role, and never authorize an automatic takeover.
  - **Option B (Authoritative Liveness):** Treat `process_observed` or `recent_activity` as equivalent to an authenticated `sessions heartbeat`.
- **Recommendation:** **Option A**, because filesystem mtimes and `ps` matches lack cryptographic/session authentication and can suffer from PID reuse or stale open file descriptors.

### Q-E: Delivery to Interactive Sessions (Pull-Only Mailbox vs Push) & Panel Placement (`16.9` vs New Tab)
- **Context:** How should messages and handoffs reach an interactive session, and where should the cross-workspace panel live?
- **Options:**
  - **Option A (Pull-Only Mailbox + Pending Handoff Record + UI/OS Notification for the Human; Dedicated `Workspaces Fleet` Tab — Recommended):**
    1. **Zero prompt injection:** Never send `SendMessage` or inject prompts into a live interactive session. Messages land in the pull-only mailbox; reassignments toward an interactive session write a `pending_handoff` record; the human receives a UI/OS notification and the session sees a 1-line notice on its next CLI/MCP call.
    2. **Panel placement:** Remediate the `16.9` read-only overview gap and add interactive fleet controls in a dedicated top-level **`Workspaces Fleet`** tab in Web UI / VS Code (plus a VS Code sidebar TreeView).
  - **Option B (Push via Claude `SendMessage` Relay + Dropdown Switcher inside Backlog):** Relay nudges into live Claude sessions via `claude -p` and place "All Workspaces" inside the existing Backlog project switcher.
- **Recommendation:** **Option A**, eliminating all cross-session prompt injection vectors while giving the owner a dedicated fleet control plane.

### Q-F: Authority Matrix — Who May Claim, Hand Off, Take Over, Reassign, and Clean Up (and Human-Owner Proof)
- **Context:** Which actors may perform each role/registry mutation, and how should the broker/UI verify that an owner-only action was genuinely clicked by the human owner rather than called by a local agent reading `~/.config/ai-orchestration/ui-token`?
- **Options:**
  - **Option A (Strict Role Authority + OS/Extension-Host Human Confirmation for Owner-Only Actions — Recommended):**
    - *Claim missing role:* self-identifying session in that workspace, or Owner.
    - *Voluntary handoff:* current role holder (matching `fencing_token`), or Owner.
    - *Stale takeover:* Owner, or holder-declared lease expiry (never an uninvited agent).
    - *Active reassignment:* Owner or Current Holder only (forbid agent `--force` takeover).
    - *Registry cleanup / unregister / quarantine:* Owner only, reversible via `.trash/`.
    - *Human-owner proof:* In VS Code, gate owner-only actions behind a native Extension Host modal (`vscode.window.showInformationMessage(..., { modal: true })`); in the Web UI / Broker, gate them behind a native OS dialog (`osascript` on macOS) or a one-time human confirmation code not readable via agent API/file tools.
  - **Option B (Trust Local `ui-token` + Allow Agent `--force` Reassign):** Treat any caller presenting `ui-token` or `--force` as authorized.
- **Recommendation:** **Option A**.

### Q-G: Liveness Dimensions for Display vs Takeover Eligibility
- **Context:** Replacing the single `active | stale` status with unambiguous signals so `orchestrator status` and `sessions role` never contradict each other.
- **Options:**
  - **Option A (Four Explicit Signals: `heartbeat_valid`, `recent_activity`, `process_observed`, `takeover_eligible` — Recommended):**
    - Display all four signals clearly in the UI and CLI JSON.
    - Define `takeover_eligible = true` only when `role_state == missing`, or the current holder explicitly declared `draining`/`stopped`, or `heartbeat_valid == false` for longer than `takeover_threshold_sec` (default 1800s for headless, owner-confirmed only for interactive).
  - **Option B (Keep Single `active | stale` String with Longer Timeout):** Keep a single status string and simply increase `DEFAULT_STALE_TIMEOUT_SEC` from 300s to 3600s.
- **Recommendation:** **Option A**, because it separates what the protocol knows (`heartbeat_valid`), what local hints suggest (`recent_activity`, `process_observed`), and what policy permits (`takeover_eligible`).
