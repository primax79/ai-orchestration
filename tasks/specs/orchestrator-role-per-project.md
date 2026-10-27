# Spec — Orchestrator role per project, with workspace fallback

> **Status:** Draft v2 (2026-10-28) after reviews by Codex and ai-coding-tools-58; re-checked OK by 58 (all 7 points).
> **Owner decision (2026-10-28, note N074):** "gli orchestrator sono per progetto": there is an orchestrator role **per
> project**; a project without its own orchestrator is handled by the **workspace orchestrator** (fallback).
> **Builds on:** `orchestrator-control-plane-study.md` (T073: authority matrix, pull-only mailbox, liveness dimensions,
> transactional succession) — this spec changes the KEY of the role, extends the stores and event/trigger/mail routing
> to per-key isolation, and merges its implementation plan into Initiative 18 (`18.1..18.8`). Supersedes "one
> orchestrator per workspace" in `events-and-triggers.md` §0 and `orchestration-broker-mcp.md` (mail address).
> **Absorbs/relates:** T079 (workspace/project resolution from a subdirectory), T083 (provider id is the identity),
> T071 (registration hint), 16.7/16.8 (broker workers, mail). N068 is already fixed by T070 (done 2026-10-27).

## 0. Why

On 2026-10-27/28 in workspace `ai-coding-tools`, two legitimate orchestrators (`ai-coding-tools-87` for
`ai-orchestration` + `ai-swissknife`, `ai-coding-tools-58` for `git-code-rag`) could not both be registered: when `58`
ran `sessions register --role orchestrator` from the workspace root without `--project`, the single workspace role was
silently taken over by `58` (generation 4) and had to be handed back (generation 5). UI, mail, verification queues, and
handoff could address only one holder per workspace.

## Decisions

Recorded architect decisions (the owner may override):

- **Durable key = project uuid; slug for display/address.** Role keys are `(workspace_uuid, project_uuid)` (with
  `project_uuid = "_workspace"` for the workspace-level role). Mutable project slugs are used for CLI/UI display and
  addressing, resolved to `project_uuid` against the registry.
- **Cutover: queued/running turns complete with the holder that owned them at enqueue; new events follow the new
  resolution after the watermark.** Claiming or releasing a project key records a cutover watermark (`event_seq`) under
  the lock without moving or aborting in-flight/queued fallback turns.
- **No holder anywhere: park durably + UI + manual claim.** When neither the project key nor `_workspace` has an active
  holder, events and mail for that key are parked durably in the key's queue/mailbox, surfaced prominently in the UI,
  and wait for a manual claim or owner assignment.
- **Project removed: role state quarantined (reversible) with its queue and history; renamed: key unchanged, alias
  kept; becomes inner workspace: old role fenced and quarantined, new workspace starts at generation 1 with the history
  linked.** Unregistering the inner workspace reverses the transition by restoring/re-linking the quarantined outer key
  or starting a fresh project key with linked history.
- **Liveness: one session heartbeat + per-key activity shown; no per-key heartbeat requirement.** A single
  `sessions heartbeat` refreshes the session's `last_seen`; per-key activity (`last_turn_at`, `last_action_at`) is
  tracked and displayed separately so "claim many keys, then ignore one" is visible without requiring N heartbeats.
- **Bulk: `--project` repeatable only for `register`/`status`.** All other role lifecycle mutations (`claim`,
  `hand-off`, `accept-handoff`, `release`, `takeover`, `reassign`, `rotate`, `enqueue`, `queue`) act on **one** key per
  invocation.
- **Bare `workspace` mail with no `_workspace` holder: parked.** Mail addressed to bare `workspace` targets the
  `_workspace` key specifically; if `_workspace` has no holder, the message is parked durably and surfaced in the UI
  (never routed to an arbitrary project holder).
- **No silent default to `_workspace` on mutations:** Running `sessions register --role orchestrator` or any role
  mutation from a directory that resolves to the workspace root (`_workspace`) without an explicit `--project` is
  refused; the caller must pass `--project <slug>` or `--project _workspace`.

---

## 1. Role Key, Registry Lifecycle, and Resolution

### 1.1 Durable Identity vs. Display Slug
- In `scripts/orchestration_registry.py:261`, the `projects` table defines an immutable `uuid TEXT PRIMARY KEY` alongside
  mutable `(workspace_uuid, slug)` and `(workspace_uuid, rel_path)`. Furthermore, `plan_projects_discover()`
  (`scripts/orchestration_registry.py:1315`) can derive a new slug if a folder is renamed or deduplicated, and
  `apply_projects_discover()` (`scripts/orchestration_registry.py:1415`) executes `DELETE FROM projects WHERE
  workspace_uuid = ?` followed by re-insertion.
- Therefore, every durable orchestrator role state, queue, turn directory, trigger cursor, and session holding is keyed
  by **`(workspace_uuid, project_uuid)`**, where `project_uuid` is either:
  - the canonical project UUID from `projects.uuid` / `[[workspace.projects]].uuid`, or
  - the literal string `"_workspace"` for the workspace-level orchestrator role.
- Project `slug` (`id` in `orchestration.toml`) is a **display and addressing label**: CLI flags (`--project <slug>`),
  mail addresses (`workspace:project`), and `verify-by` targets accept the current `slug` (or `project_uuid` directly)
  and resolve it to `project_uuid` under lock.

### 1.2 Project Add, Rename, Move, Remove, and Quarantine
- **Add project:** Discovering/adding a project creates its `project_uuid` in `orchestration.toml` and `registry.sqlite`.
  Until a session claims `project_uuid`, its role state is `missing` and resolution falls back to `_workspace`.
- **Rename / move project (`slug` or `rel_path` changes, `project_uuid` preserved):**
  - `apply_projects_discover()` (`scripts/orchestration_registry.py:1415`) must preserve `uuid` across path/slug updates
    and record the old slug in a per-workspace `project_aliases` map (`old_slug -> project_uuid`, with timestamp).
  - Because the role is keyed by `project_uuid`, the active holder, generation, cursors, and queues remain intact with
    zero cutover needed. Mail or `verify-by` using `old_slug` resolves via `project_aliases`.
- **Remove / delete project:**
  - If a project is removed from `[[workspace.projects]]` or its directory disappears, its role entry and per-key
    directories (`roles/<project_uuid>/`) are **never deleted silently**.
  - Instead, the key transitions to `status = "quarantined_removed"`, its active generation is fenced, and its role
    state, pending queue, and turn history are moved/marked under `.ai-orchestration/orchestrator/quarantine/<project_uuid>/`
    (reversible if the project is re-added or relinked via `workspace reconcile`).

### 1.3 Nested Workspaces (Promote Project to Inner Workspace & Unregister)
- Today, registering an inner workspace (`plan_workspace_register` in `scripts/orchestration_registry.py:726` and
  `apply_workspace_register` at `:841`) detects `projects_leaving` in the outer workspace and deletes their rows from
  `projects` in SQLite (`DELETE FROM projects WHERE workspace_uuid = ? AND uuid = ?`).
- **When a project becomes an inner workspace (or moves into one):**
  1. Under the outer workspace's `orchestrator_lock`, each leaving `project_uuid` has its current generation fenced and
     its role transitioned to `status = "transferred_to_workspace"`, recording `target_workspace_uuid` and a cutover
     watermark (`event_seq`).
  2. In-flight turns in the outer workspace finish or are fenced out; queued turns and role history in the outer
     workspace are quarantined (`quarantine/<project_uuid>/`) with a forward link `transferred_to: <inner_ws_uuid>`.
  3. The newly registered inner workspace initializes its own `.ai-orchestration/orchestrator.json` with `roles["_workspace"]`
     starting at **generation 1**, storing `linked_prior_history = {outer_workspace_uuid, project_uuid, last_generation}`
     so audit trails remain connected without colliding generation numbers or event sequences across distinct event logs.
- **Reverse on `workspace unregister` of the inner workspace:**
  - When an inner workspace is unregistered and re-discovered as a project of the outer workspace, its inner
    `roles["_workspace"]` is fenced and quarantined in place, and the outer workspace either restores the quarantined
    `roles[project_uuid]` (bumping `generation + 1` on next claim) or links the inner workspace history into the outer
    project key.

### 1.4 Resolution Function (`resolve_orchestrator(workspace_uuid, project_uuid)`)
- **Who orchestrates project `P` (`project_uuid != "_workspace"`):**
  1. If `roles[P]` has an active holder (`status` in `active`, `idle`, `pending_handoff`, `rotating` — i.e., not
     `missing`, `released`, `stopped`, `quarantined_removed`, or `transferred_to_workspace`), **P's own holder** is the
     resolved orchestrator (`resolution_source = "project"`).
  2. Otherwise, if `roles["_workspace"]` has an active holder, the **`_workspace` holder** is the resolved orchestrator
     (`resolution_source = "workspace_fallback"`).
  3. Otherwise, **none** (`resolution_source = "none"`, shown in UI/CLI as `"no orchestrator"`).
- **Invariants:**
  - A live or stale (`heartbeat_valid = false`) holder of `P` is **never** overridden by the `_workspace` holder during
    resolution. Liveness affects display and `takeover_eligible` (§5), never resolution.
  - Only an explicit `orchestrator release --project P` (by the holder or owner) or an owner reassignment/quarantine
    returns `P` to `_workspace` fallback. The automatic takeover of an inactive interactive holder by a configured
    headless standby (§4.4, Q025) changes the holder of `P`, not the resolution rule.

### 1.5 Scope of `_workspace` vs. Project Holders (and Pointer Tasks)
- **Workspace role (`_workspace`) scope:** `_workspace` tasks, inbox triage of the workspace registry, cross-project
  coordination (workspace tasks with `coordinates:` refs), and fallback orchestration for projects without their own
  holder. It does **not** dispatch into a project that has its own holder; it may send that holder mail.
- **Project role (`P`) scope & Pointer Tasks rule:**
  - A holder of project `P` owns all tasks, questions, use cases, and inbox notes inside `P`'s `tasks/` tree.
  - **Workspace pointer tasks exception:** A holder of project `P` **may** edit and transition tasks in the workspace
    root (`_workspace` `tasks/`) **if and only if** the workspace task is a pointer/coordination task that explicitly
    targets `P` — specifically, a moved pointer task (`state == "moved"` or `moved-to` referencing `P/<ID>`, see
    `tasks_engine.py:8801, 22312`) or a workspace task whose `paths` are exclusively under `P/` or whose `coordinates`
    field (`tasks_engine.py:1045`) names `P/<ID>` (e.g., workspace `T023` pointing to `git-code-rag`).
  - The exception holds whatever the pointer task's state, including one already `done`/closed: `P`'s holder may
    mirror the final state of the project task onto it (review by ai-coding-tools-58).
  - Attempting to mutate any other `_workspace` task from a session that holds only project `P` (and not `_workspace`)
    is **refused** with `error = "outside_project_role_scope"` (and a hint to message `workspace` via mail or pass
    `orchestrator.ask`).

---

## 2. Storage Architecture, Schema Gate, and Transactional Cutover

### 2.1 Current Storage Inventory (v1 Code Baseline)
Today, single-orchestrator assumptions are spread across five stores:
1. **`orchestrator.json` (`scripts/orchestration_orchestrator.py:170, 772`):** Single top-level object with scalar
   `role`, `generation`, `status`, `fencing_token`, `cursor`, `delivery_cursor`, `trigger_scan_cursor`, and `current`.
2. **Queue & Turns directories (`scripts/orchestration_orchestrator.py:157-168, 899`):** Single flat
   `.ai-orchestration/orchestrator/queue/` and `.ai-orchestration/orchestrator/turns/` shared by the whole workspace.
3. **Trigger cursor & batches (`scripts/orchestration_orchestrator.py:663`, `scripts/orchestration_triggers.py:626, 1592`):**
   `.ai-orchestration/triggers/cursor.json` indexed by `role = "orchestrator"` and `triggers/batches/batch-orchestrator-*`
   scanning a single stream into a single queue (`_enqueue_orchestrator_turn` at `orchestration_triggers.py:944`).
4. **Session records (`scripts/orchestration_sessions.py:301-348, 501-520, 589`):** `.ai-orchestration/sessions/<id>.json`
   stores scalar `"role": "orchestrator"`, `"generation": int`, `"cursor": int`. On succession (`:314`), the old
   session's entire record is marked `"status": "retired"`; on `deregister_session` (`:589`), it checks a single
   `orch_doc["current"]["session_id"]`.
5. **Turn completion fencing (`scripts/orchestration_orchestrator.py:1607-1628`):** Checks a single top-level
   `fresh_orch.get("generation", 1) != generation`.

### 2.2 v2 Multi-Key Storage Layout & Schema Version Gate
All five stores move to schema version **2** (`"schema_version": 2`):

- **`orchestrator.json` (`schema_version: 2`):**
  ```json
  {
    "schema_version": 2,
    "min_reader_version": 2,
    "min_writer_version": 2,
    "migration_epoch": 1,
    "workspace_uuid": "52c62ed7-47c6-45e0-8136-6aa92350e4de",
    "project_aliases": {
      "old-slug": {"project_uuid": "<uuid>", "aliased_at": "2026-10-28T..."}
    },
    "roles": {
      "_workspace": {
        "key": "_workspace",
        "project_slug": "_workspace",
        "generation": 5,
        "status": "active",
        "fencing_token": "fence-_workspace-g5-...",
        "cutover_watermark_seq": 142,
        "delivery_cursor": 142,
        "trigger_scan_cursor": 142,
        "last_turn_at": "2026-10-28T...",
        "last_action_at": "2026-10-28T...",
        "current": {
          "registry_session_id": "ai-coding-tools-87",
          "provider_session_id": "5865a698-...",
          "display_name": "ai-coding-tools-87",
          "tool": "claude",
          "kind": "interactive",
          "model": "claude-opus-5-5",
          "started": "2026-10-28T...",
          "turns": 12
        },
        "pending_handoff": null,
        "linked_prior_history": null
      },
      "<project_uuid>": { "...same per-key structure..." }
    }
  }
  ```
- **Per-key directories under `.ai-orchestration/orchestrator/roles/<key>/`:**
  - `roles/<key>/queue/<seq>-<turn_id>.json` — queued and running turns for `<key>`.
  - `roles/<key>/turns/<turn_id>/turn.json` — completed/dead turn records and stream logs for `<key>`.
  - `roles/<key>/handoffs/gen-<N>.md` — pull-only handoff bundles for `<key>`.
  - `roles/<key>/parked/` — durably parked event batches and mail when `<key>` and `_workspace` both lack a holder.
  - `quarantine/<key>/` — quarantined state/queue/turns for removed or transferred projects.
- **Trigger cursors & batches (`triggers/cursor.json` `schema_version: 2`):**
  - Keyed by `orchestrator:<key>` (e.g., `orchestrator:_workspace`, `orchestrator:<project_uuid>`), with batch files
    named `batch-orchestrator-<key>-<first_seq>-<last_seq>-<hash>.json`.
- **Session records (`sessions/<id>.json` `schema_version: 2`, §4.3):**
  - Replace scalar `role`/`generation` role ownership with `holdings: dict[key, HoldingRecord]`.

### 2.3 Versioned Migration, Exclusive Migration Epoch, and Legacy-Writer Refusal
- **Exclusive migration lock & epoch:** Migration (`ai-orch orchestrator migrate-v2 [--dry-run | --apply --expect-hash <h>]`)
  acquires `orchestrator_lock`, `session_lock`, and `event_lock` in canonical order (`orchestrator.py:207`), increments
  `migration_epoch`, snapshots a full backup to `.ai-orchestration/backups/pre-v2-<timestamp>/`, and atomically writes
  `schema_version: 2` across `orchestrator.json`, `triggers/cursor.json`, and all `sessions/*.json`.
- **What migration does:**
  1. Moves top-level v1 `orchestrator.json` state into `roles["_workspace"]` with its `generation`, `fencing_token`,
     `delivery_cursor`, and `trigger_scan_cursor` intact.
  2. Moves existing `.ai-orchestration/orchestrator/queue/*` and `turns/*` into `roles/_workspace/queue/` and
     `roles/_workspace/turns/`. In-flight turns running across the migration carry `key = "_workspace"` and remain fenced
     by `roles["_workspace"].fencing_token`.
  3. Upgrades every `sessions/*.json` record: if `role == "orchestrator"` and `status != "retired"`, populates
     `holdings["_workspace"] = {project_uuid: "_workspace", generation, fencing_token, state: "active", ...}`.
  4. Upgrades `triggers/cursor.json` entry `"orchestrator"` to `"orchestrator:_workspace"`.
- **Refusal of legacy writers (preventing silent overwrite by old code):**
  - A v1 client (`scripts/orchestration_sessions.py:301` or `orchestration_orchestrator.py`) expects top-level
    `orch_doc["current"]` and `orch_doc["generation"]`; if it ran against a v2 file without a gate, it would overwrite
    `orchestrator.json` with a top-level v1 structure or fail partway.
  - All readers/writers in v2 check `doc.get("schema_version", 1)`: if a writer encounters `min_writer_version > SUPPORTED`,
    it aborts immediately with `UnsupportedSchemaVersionError` before touching any file.
  - Additionally, v2 removes top-level `"current"` and `"generation"` from `orchestrator.json` and replaces top-level
    `"status"` with `"status": "schema_v2_multi_key"` and `"legacy_v1_notice": "Use ai-orch >= v2"`, plus moves the
    lock path to `.ai-orchestration/orchestrator/.lock.v2` while leaving a read-only sentinel or advisory lock on `.lock`
    during migration so any un-upgraded v1 process fails closed instead of corrupting v2 state.
  - Rollback command (`ai-orch orchestrator rollback-v1 --apply`) restores `.ai-orchestration/backups/pre-v2-<timestamp>/`
    if no project-specific keys (`key != "_workspace"`) have been claimed yet.

### 2.4 Transactional Cutover Watermark (Claim & Release)
When project `P` transitions between fallback (`_workspace`) and having its own holder (`roles[P]`):
1. **Cutover watermark under lock:** Under `orchestrator_lock(ws)` + `event_lock(ws)`, the mutation reads `latest_seq`
   from the event log (`orchestration_events.py`) and writes `cutover_watermark_seq = latest_seq` into `roles[P]` (and
   emits `orchestrator.claimed` or `orchestrator.released` at `seq = latest_seq + 1` with `workspace_uuid` and
   `project_uuid = P`).
2. **Queued and running turns STAY with the enqueue-time holder:**
   - Turns already queued or running in `roles/_workspace/queue/` (enqueued for events with `seq <= cutover_watermark_seq`)
     **stay in `roles/_workspace/queue/`** and complete under the `_workspace` holder that owned them at enqueue time.
   - Similarly, on `orchestrator release --project P`, any turn already running in `roles/P/queue/` finishes or is
     fenced under `P`'s generation; queued unread turns in `roles/P/queue/` either drain if `--drain` was passed or are
     re-enqueued into `roles/_workspace/queue/` with an explicit `requeued_from_key: P` provenance marker and deduplicated
     by `(event_seq, rule_name)`.
3. **New events after the watermark:** Any event with `seq > cutover_watermark_seq` is routed by the trigger scanner to
   the new resolved key (`roles[P]` after claim; `roles["_workspace"]` after release).
4. **Per-key generation fencing on turn completion:**
   - `run_next_turn` (`scripts/orchestration_orchestrator.py:1607`) is parameterized by `key` (`project_uuid` or
     `"_workspace"`). On completion under `orchestrator_lock(ws)`, it loads `fresh_role = fresh_orch["roles"][key]` and
     verifies both `fresh_role["generation"] == turn_record["generation"]` and
     `fresh_role["fencing_token"] == turn_record["fencing_token"]`. A rotation on key `A` never invalidates an in-flight
     turn on key `B`.
5. **Cross-queue replay & idempotency:**
   - Firing records (`triggers/firings/<firing_id>.json`, `orchestration_triggers.py:616, 1626`) include `target_key` in
     the record metadata while keeping `firing_id = make_firing_id(rule_name, ev_seq, ev_id)` workspace-unique per
     `(rule_name, ev_seq, ev_id)`. Thus, an event settled before `cutover_watermark_seq` in `_workspace` is never
     re-fired into `roles[P]` after cutover.
6. **Neither project nor `_workspace` has a holder (Durable Parking):**
   - If `resolve_orchestrator(ws_uuid, P)` returns `none`, matching trigger firings and incoming mail are written as
     durable parked records under `roles/<P>/parked/` (or `roles/_workspace/parked/` for workspace-level items).
   - `trigger_scan_cursor` advances only after the parked record is fsynced to disk.
   - The Web UI and VS Code Fleet/Project panels display a prominent `"Parked items waiting for orchestrator (N)"` badge
     with a 1-click `[Claim Role & Process Parked Queue]` action. When a holder claims `P` (or `_workspace`), parked
     items are promoted into `roles/<resolved_key>/queue/` in `seq` order.

---

## 3. Event Schema, Trigger Routing, Mail Addressing, and Verification Queue

### 3.1 Canonical Project Scoping on Events
- **Current gap:** `emit()` in `scripts/orchestration_events.py:492-506` writes `seq`, `id`, `ts`, `type`, `source`,
  `payload`, `subject`, `origin_session`, `session`, `actor`, `correlation_id`, `schema_version` — **no `project` or
  `workspace` field**. `read_events()` (`:741`) cannot filter by project. And `_emit_event()` in `tasks_engine.py:4309`
  emits `task.created` (and other `task.*` / `question.*` / `inbox.*` events) without identifying which project's
  `tasks/` tree emitted it!
- **v2 requirement:**
  1. Every event envelope in `orchestration_events.py:492` gains two mandatory top-level fields:
     - `"workspace_uuid": str` (from the workspace registry / config),
     - `"project_uuid": str` — either the canonical `project_uuid` of the project whose tree/role emitted the event, or
       `"_workspace"` for workspace-scoped events,
     - plus display `"project_slug": str` (`"_workspace"` or the project's current slug at emit time).
  2. In `tasks_engine.py`, `_emit_event(tasks_dir, ...)` resolves `tasks_dir` through `resolve_workspace_for_path(tasks_dir)`
     (`scripts/orchestration_registry.py:1507`) so every `task.*`, `question.*`, `use_case.*`, and `inbox.*` event
     carries the exact `(workspace_uuid, project_uuid, project_slug)` of that `tasks_dir`.
  3. **Explicit `_workspace` classification for unscoped/workspace events:** Events that concern the workspace as a
     whole (`workspace.*`, workspace-root `task.*`/`inbox.*`, `config.changed` on workspace config) explicitly set
     `project_uuid = "_workspace"`. Legacy v1 events in historical chunks that lack `project_uuid` are classified as
     `project_uuid = "_workspace"` by `read_events()`.
  4. `read_events()` (`scripts/orchestration_events.py:741`) gains `project_uuid: str | set[str] | None = None` filtering.

### 3.2 Trigger Evaluation & Per-Key Routing
- In `scripts/orchestration_triggers.py:1592` and `:944`, trigger scanning and turn enqueueing become key-aware:
  - For each event `ev` with `ev_project = ev.get("project_uuid") or "_workspace"`:
    - Determine the target role key at evaluation time: if `ev_project != "_workspace"` and `ev.seq <= roles[ev_project].cutover_watermark_seq`
      (from before the project role was claimed), use the pre-watermark resolution; otherwise resolve via
      `resolve_orchestrator(ws_uuid, ev_project)` (§1.4).
    - If resolved to an active key `K` (`P` or `"_workspace"`), `_enqueue_orchestrator_turn` enqueues into
      `roles[K]/queue/` under `orchestrator_lock(ws)`.
    - If resolved to `none` (neither `P` nor `_workspace` has a holder), write to `roles[ev_project]/parked/` (§2.4).
  - Delivery to interactive holders remains strictly **pull-only** (T073 Q-E: mailbox/queue notice on next CLI/MCP call
    + UI/OS notification, never prompt injection).
  - For headless holders (`16.7`), the broker runs at most one active turn worker **per key `K`** that has a headless
    holder, serialized by a per-key worker lock under `roles[K]/`.

### 3.3 Mail Addressing Grammar (`16.8` Integration)
Mail (`16.8`, currently `open`; surface defined in `tasks/specs/orchestration-broker-mcp.md:93`) is extended before `16.8`
is implemented:
- **Address grammar:**
  1. `workspace:<ws_slug>:<project_slug>` (or `workspace:<ws_uuid>:<project_uuid>`, or shorthand `<ws_slug>:<project_slug>`):
     addresses project `P` in workspace `W`.
  2. `workspace:<ws_slug>` (or bare `<ws_slug>`): addresses the **`_workspace` orchestrator role** of workspace `W`
     specifically.
  3. `<ws_slug>/<console_name>` (or `workspace:<ws_slug>/<console_name>`): addresses a specific registered console/session
     mailbox (`orchestration-broker-mcp.md` §5).
- **Resolution & routing rules at send time:**
  - For `workspace:project`: resolve `<project_slug>` to `project_uuid` (checking `projects` first, then
    `project_aliases` for renamed projects; §1.2). Store the immutable `target_project_uuid` in the mail envelope.
    Route to `resolve_orchestrator(ws_uuid, project_uuid)`: if `P` has a holder, deliver to `P`'s mailbox; else if
    `_workspace` has a holder, deliver to `_workspace`'s mailbox (tagged `for_project: <project_slug>`); else **park
    durably** in `roles[project_uuid]/parked/mail/` and show in UI.
  - For bare `workspace` (`<ws_slug>` without `:project`): targets `roles["_workspace"]` **only**. If `roles["_workspace"]`
    has no holder, the message is **parked durably** in `roles["_workspace"]/parked/mail/` and surfaced in the UI for
    manual claim — it is **never** routed to a random project holder.

### 3.4 Verification Queue Addressing (`verify-by` & `verification-queue --for`)
- **Current state:** `match_verify_by()` and `get_verification_queue()` (`tasks_engine.py:14639-14894`) match `verify-by`
  only against workspace slugs (`workspace:<ws_slug>` or `<ws_slug>`) and `session:<prefix>`.
- **v2 specification:**
  1. **`verify-by` value grammar:** A task's `verify-by` field accepts:
     - `workspace:<ws_slug>:<project_slug>` or `<ws_slug>:<project_slug>` (or within the same workspace, `project:<project_slug>`)
       — targets the orchestrator of that specific project key;
     - `workspace:<ws_slug>` or bare `<ws_slug>` — targets the **`_workspace` holder** of `<ws_slug>`;
     - `session:<session_name_or_id>` or a registered session display name (e.g., `ai-coding-tools-58`) — targets that
       session (resolved across provider-id renames via T083).
  2. **`tasks verification-queue --for <target>` resolution:**
     - `--for <ws_slug>:<project_slug>` returns delivered tasks whose `verify-by` resolves to `(ws_uuid, project_uuid)`
       (including tasks addressed to the current holder session's display name or `provider_session_id`).
     - `--for <ws_slug>` (bare workspace slug) returns tasks whose `verify-by` is bare `<ws_slug>` / `workspace:<ws_slug>`,
       plus tasks targeting projects in `<ws_slug>` that currently have **no project holder** and therefore fall back to
       the `_workspace` holder. It does **not** claim tasks addressed to `<ws_slug>:<P>` when `P` has its own holder.
     - `--for <session_name>` returns tasks addressed to `session:<session_name>` or to any `(ws_uuid, project_uuid)` key
       currently held by that session.

---

## 4. Authority Contract, Multi-Key Sessions, Liveness, and Release

### 4.1 T073 Authority Contract Applied Per Key
Every rule from `orchestrator-control-plane-study.md` Topic 2 & Topic 5 (`Q-F`) applies **per key `K`** (`project_uuid`
or `"_workspace"`):
- **Single-key mutation rule:** All role lifecycle mutations (`claim`, `hand-off`, `accept-handoff`, `release`,
  `takeover`, `reassign`, `rotate`, `enqueue`) operate on **exactly one key `K`** per command invocation. Multi-key
  atomic mutations are forbidden (except `sessions register --role orchestrator` and read-only `orchestrator status`,
  which accept repeatable `--project`; §4.5).
- **CAS & fencing preconditions on every succession:**
  - Every mutation requires `expect_generation == roles[K].generation` under `orchestrator_lock(ws)`.
  - **Claim (`roles[K].status` in `missing | released | stopped`):** Allowed for a self-identifying session
    (`(tool, provider_session_id)`) or the Owner. Bumps `roles[K].generation` (`0 -> 1` on first claim, or `N -> N+1`
    after a release) and issues a fresh per-key `fencing_token`.
  - **Voluntary handoff (`orchestrator hand-off --project K --to ...`):** Allowed only for the **current holder of `K`**
    (verified by matching `roles[K].current.provider_session_id` / `registry_session_id` **and** `roles[K].fencing_token`)
    or the **Owner**. Toward an interactive session, writes `roles[K].pending_handoff` and
    `roles/<K>/handoffs/gen-<N+1>.md` (pull-only, zero prompt injection); target activates via
    `orchestrator accept-handoff --project K --expect-generation <N+1>`.
  - **Voluntary release (`orchestrator release --project K [--reason "..."]`):** Allowed for the **current holder of `K`**
    (matching `fencing_token` + `expect_generation`) or the **Owner**. Sets `roles[K].status = "released"`, clears
    `roles[K].current`, records `cutover_watermark_seq` (§2.4), and removes `K` from the session's active `holdings`.
    For `K != "_workspace"`, resolution immediately falls back to `roles["_workspace"]` at the watermark.
  - **Reassign (`orchestrator reassign --project K ...`):** Requires preview diff + `expect_plan_hash` +
    `expect_generation`. Allowed only for the **Owner** (via authenticated owner confirmation, T073 `Q-F`) or the
    **current holder of `K`** (voluntary switch). Pre-image of `orchestration.toml` (`[projects.<slug>.routing]` or
    workspace routing) is saved and rolled back if headless bootstrap fails.
  - **No agent `--force` takeover of a live holder:** An agent session cannot take over a key held by another session.
    Stale takeover (`takeover_eligible == true`) is restricted to the **Owner** or prior holder-declared lease expiry.

### 4.2 In-Flight Delegated Runs in Handoff / Reassign / Release Payloads (Cross-Repo `kilo-mcp` Requirement)
- When a key `K` (`workspace:project` or `workspace:_workspace`) is handed off, reassigned, or released, the generated
  handoff bundle (`roles/<K>/handoffs/gen-<N+1>.md` and the JSON payload returned by `hand-off`, `reassign`, `release`)
  must include a **computable `in_flight_runs` list** for key `K`:
  - Each entry records `{run_id / kilo_task_id, tool, project_uuid, project_slug, task_id, worktree_path, branch, status}`.
- **How `in_flight_runs` is computed:**
  1. Local UI/CLI runs (`.ai-orchestration/runs/<run_id>/run.json`) carry `workspace_uuid` and `project_uuid`.
  2. **Cross-repo requirement on `kilo-mcp`:** Delegated `kilo_implement` runs must be tagged with the dispatching key
     (`dispatch_key = "<workspace_slug>:<project_slug>"` and `workspace_uuid` / `project_uuid`, passed in metadata or
     inferred from `working_directory` via the registry resolver) and persisted in `kilo-mcp`'s task store so
     `ai-orch` can query active/running `kilo-mcp` tasks filtered by `(workspace_uuid, project_uuid)`. *(Tracked as a
     cross-repo task on `kilo-mcp` in §6).*

### 4.3 Many-to-Many Sessions & Provider Identity (`T083`)
- **Identity is `(tool, provider_session_id)` (`T083`):**
  - A session is uniquely identified by `(tool, provider_session_id)` (`scripts/orchestration_sessions.py`).
  - If a session re-registers or is renamed by the host client (e.g., `ai-coding-tools-c1 -> ai-coding-tools-d8` or
    `ai-coding-tools-58`) with the same `(tool, provider_session_id)`, `register_session` updates `display_name` (and
    records the old name in `name_history`) in place **without** bumping `generation` on any held key, and updates
    `roles[K].current.display_name` across all keys `K` held by that session so `orchestrator status` always shows the
    current human-readable name.
- **Many-to-many `holdings` in `sessions/<id>.json` (`schema_version: 2`):**
  - Today, `scripts/orchestration_sessions.py:314` marks the entire session `"status": "retired"` when it loses the single
    orchestrator role, and `:589` updates only a single `orch_doc["current"]` on deregistration.
  - In v2, a session record holds a map of keys:
    ```json
    "holdings": {
      "<project_uuid_or__workspace>": {
        "project_uuid": "<project_uuid_or__workspace>",
        "project_slug": "git-code-rag",
        "generation": 1,
        "fencing_token": "fence-...",
        "state": "active",
        "claimed_at": "2026-10-28T...",
        "last_action_at": "2026-10-28T...",
        "cursor": 142
      }
    }
    ```
  - **Isolation across keys held by the same session:**
    - Releasing, handing off, or being superseded on key `K1` marks `holdings[K1].state = "released" | "retired"` (with
      timestamp and reason), **never** retiring the session record itself (`session.status` stays `"active"`) and
      **never** touching `holdings[K2]` for any other key `K2` the session holds.
    - A session transitions to `session.status = "retired"` only when it explicitly runs `sessions deregister` (which
      releases/marks deregistered all its remaining `holdings`), or when all of its holdings have been retired and the
      session itself is closed.

### 4.4 Liveness Per Session and Activity Per Key (Using T073 Thresholds)
- **Session-level heartbeat (no per-key heartbeat burden):**
  - `ai-orch sessions heartbeat` refreshes `session.last_seen` once for the session, which validates `heartbeat_valid`
    across all keys currently held by that session.
- **Per-key activity tracking (`last_turn_at`, `last_action_at`):**
  - Every key `roles[K]` independently tracks `last_turn_at` (last orchestrator turn completed on `K`) and
    `last_action_at` (last CLI/MCP task/question/inbox/orchestrator command executed against project `K` by its holder).
  - `orchestrator status` and the Fleet UI display **both** the session's `heartbeat_valid` (`last_seen`) and the key's
    `key_last_action_at` so an operator can immediately see if a session claimed 3 projects and is actively working in 1
    while ignoring the other 2.
- **Thresholds (strictly from T073 `orchestrator-control-plane-study.md` Topic 1 & `Q-G`, configurable in `orchestration.toml`):**
  - `heartbeat_ttl_sec`: per session kind. Headless default **`300` seconds** (`DEFAULT_STALE_TIMEOUT_SEC = 300.0` in
    `scripts/orchestration_sessions.py:51`); interactive default **`7200` seconds** (`[orchestrator]
    heartbeat_ttl_sec_interactive`), because interactive sessions heartbeat only at their own check-ins (T071) and a
    300 s TTL would show every interactive holder as stale between turns. Configurable via `[orchestrator]
    heartbeat_ttl_sec` / `heartbeat_ttl_sec_interactive` or `AI_ORCH_SESSION_STALE_TIMEOUT`.
    `heartbeat_valid = (now - session.last_seen) <= ttl(kind)`.
  - `takeover_threshold_sec`: default **`1800` seconds** for headless holders (`orchestrator-control-plane-study.md`
    §6 `Q-G` line 682, configurable via `[orchestrator] takeover_threshold_sec`).
  - **Interactive holder inactive (owner decision Q025 = B, 2026-10-28, overrides T073's recommendation A):** after
    `takeover_threshold_sec_interactive` without heartbeat or activity on key `K`, a **headless orchestrator configured
    as the key's standby** (`[projects.<slug>.routing] standby = "<headless holder>"`, or the workspace's) takes over `K`
    automatically: generation bump, fresh fencing token, `orchestrator.auto_takeover` event, notice in the former
    holder's mailbox and an owner notification. The former interactive holder is fenced; when it comes back it sees the
    takeover and may request the key back (handoff request). No standby configured: no automatic takeover (display only).
    This is a system policy with a configured standby, not an agent `--force` takeover, which stays forbidden.
  - `recent_activity` (provider transcript mtime) and `process_observed` (`ps`/`lsof` check) are **read-only display
    hints only** (`authority: "hint_only"`, T073 `Q-D`).

### 4.5 CLI Grammar, CWD Resolution (`T079`), and No Silent Default to `_workspace`
- **Consistent workspace & project resolution from `cwd` (`T079`):**
  - Every CLI group (`orchestrator`, `sessions`, `config`, `tasks`, `triggers`) resolves `cwd` using
    `resolve_workspace_for_path(cwd)` (`scripts/orchestration_registry.py:1507-1550`), which returns
    `(nearest_workspace, nearest_project)`.
- **No silent default to `_workspace` on role registration or mutations (prevents the 2026-10-28 gen 4/5 accident):**
  - If `cwd` is inside a registered sub-project `P` (`nearest_project != None`) and `--project` is omitted, `--project`
    defaults to `P['slug']` and the command prints `Resolved project key: <ws_slug>:<P_slug> (<project_uuid>)`.
  - If `cwd` is the workspace root (or any path where `nearest_project is None`, i.e., `_workspace`) and `--project` is
    **omitted**:
    - **Every role mutation** (`sessions register --role orchestrator`, `orchestrator claim`, `hand-off`,
      `accept-handoff`, `release`, `takeover`, `reassign`, `rotate`, `enqueue`) is **REFUSED** with exit code `2`
      (`error = "explicit_project_required_at_workspace_root"`).
    - The error message lists: (a) the keys this session already holds (`holdings`), (b) the registered projects in the
      workspace, and (c) the exact flags required: pass `--project <slug>` for a project role or explicit
      `--project _workspace` for the workspace fallback role.
- **`--project` repeatability rules:**
  - **Repeatable (`--project P1 --project P2` or comma-separated):** Allowed **only** on:
    1. `ai-orch sessions register --role orchestrator --project P1 [--project P2 ...]` (claims/refreshes each listed
       key where the caller is already holder or the key is `missing`/`released`; if any requested key is held by
       another session, the entire registration fails before mutating any key, naming the conflicting key and holder), and
    2. `ai-orch orchestrator status [--project P1 --project P2 ...]`.
  - **Single key only:** `claim`, `hand-off`, `accept-handoff`, `release`, `takeover`, `reassign`, `rotate`, `queue`,
    `enqueue` accept at most **one** `--project <key>`; passing multiple values is refused.
- **`orchestrator status` without `--project` (explicit read-only exception):**
  - `ai-orch orchestrator status` (with no `--project`, from any directory in the workspace) is the explicit read-only
    exception: it lists **all** keys in the workspace (`_workspace` plus every registered project `P`), showing for each
    key: `project_slug`, `project_uuid`, `status`, `resolution` (`own holder` vs `-> falls back to _workspace (<holder>)`
    vs `no orchestrator`), current `display_name` (via T083), `tool`, `kind`, `generation`, liveness signals
    (`heartbeat_valid`, `recent_activity`, `process_observed`, `takeover_eligible`), `key_last_action_at`, queued/running
    turns, and parked items count.

---

## 5. UI and VS Code Control Plane

- **Project View:** Header badge shows the resolved orchestrator for the selected project:
  - If `resolution_source == "project"`: `[Orchestrator: <display_name> (<tool>, <kind>, gen <N>)]` with liveness pills
    and `[Hand off…]`, `[Release to _workspace]`, `[Reassign…]`.
  - If `resolution_source == "workspace_fallback"`: `[Orchestrator: falls back to _workspace -> <display_name> (<tool>)]`
    with `[Claim Project Role…]`.
  - If `resolution_source == "none"`: prominent warning `[No Orchestrator — N parked items]` with `[Claim Role…]`.
- **Workspace Fleet View (`Workspaces Fleet` tab & VS Code TreeView, `18.7`/`18.8`):**
  - Expandable per-workspace rows showing `_workspace` and every project key `P`, their current holder `display_name`,
    orthogonal liveness + per-key `last_action_at`, fallback arrows, in-flight delegated runs, and parked item counts.
  - Per-key owner actions (`Prepare Pending Handoff / Reassign`, `Accept Handoff`, `Release Project Role`,
    `Quarantine / Restore Removed Project Role`, `Deposit Mail` to `workspace:project` or `workspace`).

---

## 6. Implementation Plan — Merged into Initiative 18 (`18-orchestrator-control-plane`)

This plan merges v1's `18.P1..18.P7` into T073's ordered tasks (`tasks/specs/orchestrator-control-plane-study.md` §5.2,
lines 606–618) with realistic sizes (`S`/`M`/`L`) and strict dependency ordering:

| Task ID | Title (One Task = One Commit) | Size | Depends on | Relation to Existing Tasks | Repo(s) |
| --- | --- | --- | --- | --- | --- |
| **18.1** | **Record owner decisions (`Q-A`..`Q-G` + per-project role v2 decisions) and authority/confirmation contract in specs** — Lock the per-key `(workspace_uuid, project_uuid)` model, authority matrix (`claim`, `hand-off`, `release`, `takeover`, `reassign`, `quarantine`), cutover watermark rules, pointer-task scope rule, `verify-by` grammar, and zero-prompt-injection rule across `orchestrator-role-per-project.md`, `orchestrator-control-plane-study.md`, and `events-and-triggers.md`. | S | Q025-Q031 (T073 `Q-A`..`Q-G`) | Gate before code changes | `ai-orchestration/` |
| **18.2** | **Strictly read-only `orchestrator status` invariant** — Remove `orchestrator_lock` acquisition and `_migrate_orchestrator_cursors()` file writes from `get_orchestrator_status()` (`scripts/orchestration_orchestrator.py:772-872`); move cursor migration strictly into mutating commands. | S | 18.1 | Fixes read-only status defect (`T026` follow-up) | `ai-orchestration/` |
| **18.3** | **Provider-scoped session identity `(tool, provider_session_id)` (`T083`) and many-to-many `holdings` model** — Land **T083** first (in-place `display_name` rename for same `(tool, provider_session_id)` with `name_history`); replace scalar session `role`/`generation` (`scripts/orchestration_sessions.py:314, 501, 589`) with `holdings[key] = {project_uuid, generation, fencing_token, state}` so losing/releasing one key never retires the session or its other keys; enforce retired-holding resurrection refusal and `provider_session_id: null` (`pending_first_turn`) on Claude `--no-handoff`. | M | 18.2, T083 | Completes **T083** | `ai-orchestration/` |
| **18.4a** | **Consistent workspace/project resolver (`T079`), CLI `--project` rules, and workspace-root mutation refusal** — Reuse `resolve_workspace_for_path()` (`scripts/orchestration_registry.py:1507`) across `orchestrator`, `sessions`, `config`, `tasks`, and `triggers`; refuse `sessions register --role orchestrator` and any role mutation from `_workspace` cwd when `--project` is omitted (printing current `holdings` and registered projects); allow repeatable `--project` only on `register` and `status`; make `status` without `--project` list all keys and fallback arrows. | M | 18.3, T079 | Completes **T079** | `ai-orchestration/` |
| **18.4b** | **Schema v2 migration across all stores, legacy-writer rejection, and canonical event/trigger/verify-by project scoping** — Upgrade `orchestrator.json`, `roles/<key>/{queue,turns,handoffs,parked}`, `triggers/cursor.json`, and `sessions/*.json` to `schema_version: 2` under an exclusive migration epoch with backup/rollback (`rollback-v1`) and legacy v1 writer refusal; add mandatory `workspace_uuid` + `project_uuid` (`_workspace` for unscoped) to `orchestration_events.py:492`, `read_events()` (`:741`), and `tasks_engine.py:4309`; enforce the workspace pointer-task scope rule (`tasks_engine.py:1045, 8801`); extend `verify-by` and `verification-queue --for` (`tasks_engine.py:14639, 14766`) to `<ws>:<project>` and session names. | L | 18.4a | Schema v2 foundation | `ai-orchestration/` |
| **18.4c** | **Per-key transactional succession (`claim`, `hand-off`, `accept-handoff`, `release`, `takeover`, `reassign`), cutover watermark, durable parking, and `T071` hints** — Implement per-key `expect_generation` + `fencing_token` checks on mutations and turn completion (`orchestration_orchestrator.py:1607`); implement `orchestrator release --project P` and transactional cutover watermark (`cutover_watermark_seq`) so queued/running turns finish with their enqueue-time holder while post-watermark events route to the new resolution; park events/mail durably when neither `P` nor `_workspace` has a holder; save/restore `orchestration.toml` pre-image on failed `reassign`; include `in_flight_runs` in handoff/reassign/release payloads; piggyback `T071` missing-role and `fenced-out` notices; update `AGENTS.md` / skills templates. | L | 18.4b, T070, T072 | Consumes **T070**, **T072**; completes **T071**; updates `UC028`, adds `UC038` | `ai-orchestration/` |
| **18.4d** | **Tag `kilo_implement` runs with dispatching key (`workspace:project`) for `in_flight_runs` handoff inventory (cross-repo)** — Add `dispatch_key` (`workspace_slug:project_slug`), `workspace_uuid`, and `project_uuid` metadata to `kilo-mcp` run records and expose per-key active-run filtering so `18.4c` handoff/reassign/release payloads list in-flight `kilo-mcp` tasks, worktrees, branches, and states. | S | 18.4c | Cross-repo companion task | `kilo-mcp/` |
| **18.5** | **Per-key liveness and activity signals (`heartbeat_valid`, `key_last_action_at`, `recent_activity`, `process_observed`, `takeover_eligible`)** — Implement `compute_liveness_signals()` in `orchestration_sessions.py` using T073's configurable thresholds (`heartbeat_ttl_sec = 300`, headless `takeover_threshold_sec = 1800`, interactive owner-only); single session heartbeat refreshes `last_seen` while per-key `last_turn_at`/`last_action_at` surfaces ignored keys; provider transcript mtimes and `ps`/`lsof` remain `hint_only`. | M | 18.4c | Implements `Q-A`, `Q-C`, `Q-D`, `Q-G` | `ai-orchestration/` |
| **18.6** | **Registry reconciliation (`workspace reconcile`) for orphaned configs, renamed/removed projects, and nested-workspace role transfers** — Forward `--config-dir` to `find_project_config_path()`; handle reboot `st_dev` shift (`device_shifted`); preserve `project_uuid` and record `project_aliases` on slug rename (`orchestration_registry.py:1315, 1415`); quarantine removed projects' role state/queues reversibly (`quarantine/<project_uuid>/`); fence and transfer/quarantine project roles when registering/unregistering an inner nested workspace (`orchestration_registry.py:726, 841`). | M | 18.4b | Updates `UC030`, adds `UC041` | `ai-orchestration/` |
| **16.7** | **Per-key orchestrator workers in broker, recovery, and `orchestrator.ask` tickets** — Adapt Initiative 16's `16.7` (`tasks/16-orchestration-broker/plan.md:14`) to run one serialized broker/trigger worker per active headless key `(workspace_uuid, project_uuid)` and route `orchestrator.ask(workspace, project?, ...)` to the resolved key's queue (or parked store). | L | 16.5, T045, 18.4b, 18.4c | Initiative 16 (`16.7`) sequenced after `18.4b/c` | `ai-orchestration/` |
| **16.8** | **Workspace, project (`workspace:project`), and console mail + UI** — Adapt Initiative 16's `16.8` (`tasks/16-orchestration-broker/plan.md:19`) to resolve `workspace:project` (`slug -> project_uuid` + `project_aliases`) at send time, fall back to `_workspace` when `P` has no holder, and park durably when bare `workspace` (or fallback) has no `_workspace` holder. | L | 16.7, 18.4b, 18.4c | Initiative 16 (`16.8`) sequenced after `18.4b/c` | `ai-orchestration/` + `ai-orchestration-ui/` + `vscode-ai-orchestration/` |
| **18.7** | **Fleet read-only aggregation (`workspace fleet`), per-project orchestrator view, and `16.9` scoping fix** — Fix `ai-orchestration-ui/backend/server.py` (`3fe9d9e`) and `vscode-ai-orchestration/src/views/dashboard-panel.ts` (`dab76d0`) to pass workspace + selected project key to `orchestrator`/`sessions`; implement `ai-orch workspace fleet --json`, `GET /api/fleet`, per-project fallback badges, per-key activity/liveness display, and parked-items counters in Web UI and VS Code. | L | 18.5, 18.6 | Remedies **16.9** gap; read-only half of `UC039` | `ai-orchestration/` + `ai-orchestration-ui/` + `vscode-ai-orchestration/` |
| **18.8** | **Interactive Fleet & Per-Key control-plane actions in Web UI & VS Code** — Add owner-confirmed UI actions per key `(workspace_uuid, project_uuid)` in the `Workspaces Fleet` tab, Project header, and VS Code TreeView: `Claim Role & Process Parked Queue`, `Prepare Pending Handoff / Reassign`, `Accept Handoff`, `Release Project Role to _workspace`, `Reconciliation & Quarantine` modal, and pull-only `Deposit Mail` composer (integrated with `16.8`). | L | 18.7, 16.8 | Completes `UC039`, `UC040` | `ai-orchestration-ui/` + `vscode-ai-orchestration/` |

---

## 7. Acceptance Criteria

1. **Coexistence of project holders:** Two sessions hold different projects of one workspace at the same time;
   `orchestrator status` lists `_workspace` and every project key with their current holder `display_name`; neither
   bumps the other's generation or retires the other's session (`holdings` isolation).
2. **Workspace fallback & transactional cutover:** A project without a holder resolves to the `_workspace` holder;
   claiming the project records `cutover_watermark_seq`, leaves already-queued/running fallback turns with `_workspace`
   to finish there, and routes post-watermark events to the new project holder; `orchestrator release --project P`
   falls back to `_workspace` at the new watermark.
3. **Durable parking when no holder exists anywhere:** When neither project `P` nor `_workspace` has a holder, events and
   mail for `P` (and bare `workspace` mail when `_workspace` has no holder) are parked durably on disk and surfaced in
   the UI for manual claim.
4. **Versioned migration & legacy-writer refusal:** Migration to `schema_version: 2` preserves the existing workspace
   role's generation/cursors/queue under `roles["_workspace"]`, upgrades `sessions/*.json` and `triggers/cursor.json`,
   and refuses legacy v1 writers so old clients cannot overwrite v2 state.
5. **Subdirectory resolution & workspace-root safety:** From a project subdirectory, commands resolve to that project's
   key via `resolve_workspace_for_path` and print the resolved key (`T079`). From the workspace root without `--project`,
   `sessions register --role orchestrator` and all role mutations are **refused** (printing the session's current
   `holdings` and registered projects).
6. **Authority & handoff payload:** An agent cannot take a live holder's key (`--force` forbidden); voluntary handoff,
   release, and owner reassign include the key's `in_flight_runs` (`kilo-mcp` tasks, worktrees, branches, states) and
   check `expect_generation` + `fencing_token`.
7. **Rename resilience (`T083`) & project lifecycle:** Renaming a session's display name (`(tool, provider_session_id)`
   unchanged) updates `status` in place without bumping generation. Renaming a project slug keeps `project_uuid` and
   records an alias; removing a project or promoting it to a nested inner workspace fences and quarantines the old role
   reversibly.
8. **Real case (`ai-coding-tools` with `87` and `58`):**
   - `ai-coding-tools-87` holds `_workspace`, `ai-orchestration`, and `ai-swissknife`;
   - `ai-coding-tools-58` is registered **only** on `git-code-rag`;
   - `claude-mcp` (no project holder) falls back to `87` (`_workspace`);
   - an attempt by `58` to run `sessions register --role orchestrator` from the `ai-coding-tools` workspace root without
     `--project` is **refused** and prints that `58` currently holds `git-code-rag`;
   - an update/transition by `58` on a workspace pointer task targeting `git-code-rag` (e.g., `T023 -> git-code-rag` via
     `moved-to`, `paths`, or `coordinates`) is **allowed**, whereas an update by `58` on a non-pointer `_workspace` task
     is **refused**;
   - `verification-queue --for ai-coding-tools:git-code-rag` (or `--for ai-coding-tools-58`) returns tasks with
     `verify-by: ai-coding-tools:git-code-rag`, while bare `verify-by: ai-coding-tools` belongs to the `_workspace`
     holder (`87`).

---

## 8. Open points for the owner

- Whether the `_workspace` holder may also dispatch into a project whose holder is stale (not released) when the
  owner is away. Recommendation: no automatic dispatch; it mails the project holder and shows the project as
  "holder stale" in the UI; the owner decides.
