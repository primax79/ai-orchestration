# Architectural & Feasibility Review: Tracker Links (Draft 1)

- **Date:** 2026-10-18
- **Reviewer:** Gemini (via kilo-mcp)
- **Target Specification:** `tasks/specs/tracker-links.md` (Draft 1 2026-10-18: linking tasks to external tickets, Redmine first; n:m typed links; hybrid granularity following how work was opened; modes none/link/map/mirror; propose-then-apply; D4Science profile).
- **Referenced Skills & Specifications Checked:**
  - `tasks/specs/tracker-links.md` (Draft 1)
  - `tasks/specs/task-and-state-model.md` (§2 Formal Task Header Grammar, §3 State Machine)
  - `tasks/specs/orchestration-broker-mcp.md` (§3b Tool Contract v1)
  - `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py` (lines 38–67, 301–354, 2981–3120, 5772–5805)
  - `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/d4science-ecosystem-tools/skills/gcube-redmine-assistant/SKILL.md` (methods, pitfalls, granularity economics, deterministic snapshots)
  - `/Users/Alfredo/works/ai-coding-tools/agentic-coding-kit/plugins/third-party/skills/mcp-redmine/SKILL.md`
  - `/Users/Alfredo/works/ai-coding-tools/agentic-coding-kit/plugins/third-party/skills/redmine-rest-helper/SKILL.md`
- **Real Practice References Checked (Read-Only):**
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/release-push/T032-redmine-status-sync/` (`README.md`, `redmine_tickets_2026-09-30.md`)
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/porting-lr74/T111-newis-resources-inventory-and-migration/README.md` (57 tickets created, 3-level hierarchy, `start_date` wiping pitfall, first-example approval)
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/release-push/T010-release-tickets-17579.md` (Release Next #17579 vs LR7 #32197, SNAPSHOT tickets remaining in New)
- **Scope:** Review only — no edits to existing specs or code. Analysis across the four owner cases, porting_liferay real-world practice, granularity edge cases (expand/collapse, item tables, task movements to `done/`), relation semantics, Redmine API failure modes (field clearing, required custom fields, status workflow constraints, private notes, journals, closed issue visibility), idempotency under partial failure, notification noise, secrets handling, state persistence, profile boundaries, and open questions.

---

## Executive Summary

`tasks/specs/tracker-links.md` establishes a strong architectural direction for connecting development tasks with external ticketing systems. Its core tenets—treating the code repository as the single source of truth, enforcing a strict "propose-then-apply" protocol, adopting hybrid granularity based on how work was opened, and relying on deterministic committed snapshots (`git diff` re-alignment)—directly reflect the hard-won operational practices developed in `dave_agent` and `porting_liferay`.

However, the draft contains several **critical specification gaps and false assumptions regarding tracker APIs and engine internals** that would cause silent data loss, API failures, or schema corruption if implemented as written:

1. **Header Grammar & Engine Rejection**: The proposed `tickets:` header is omitted from `tasks_engine.py`'s `OPTIONAL_EXTENSION_FIELDS` and the broker MCP `tasks.set` contract; tasks using it will currently fail `tasks_engine.py doctor` validation.
2. **False Idempotency Assumption on Redmine REST APIs**: Redmine does not natively support `Idempotency-Key` headers or transactional rollbacks. Partial failures during bulk ticket creation (e.g. 50+ tickets as in T111) will duplicate tickets if retried without an engine-side execution ledger and subject-deduplication pre-flight checks.
3. **Destructive Interaction with `expand` and `collapse`**: Running `collapse` on an expanded folder containing a linked ticket deletes the folder's `README.md` and wipes local ticket linkage, leaving the Redmine issue orphaned with no clean way to reconcile without manual intervention.
4. **422 Validation Failures on Bulk Creation**: In Redmine instances with mandatory custom fields, required assignees, and mandatory categories (such as D4Science Portal-Revamping), the minimal creation parameters in §3 and §4 will be rejected with HTTP 422 Unprocessable Entity.
5. **Silent Field Clearing on Save (The T111 Trap)**: Full issue update payloads sent via `PUT /issues/{id}.json` cause Redmine to silently clear core fields disabled for that tracker (e.g. `start_date`), which non-admin API users cannot inspect ahead of time. Updates must be strictly minimal patch payloads.
6. **GUI Environment Key Resolution**: Listing `env:REDMINE_API_KEY` as primary guidance repeats a trap that fails silently in desktop IDEs (VS Code, Claude Desktop), where empty keys result in unauthenticated queries that hide private issues and trigger false duplicate creation proposals.

---

## Findings

### 1. Engine Grammar Violation: `tickets:` Header Field Rejection in `tasks_engine.py` and Broker Contract Omission
- **Severity:** Blocker
- **Spec Section:** §2 (lines 28–45) & §6 (lines 93–100)
- **Problem:**
  Section 2 introduces `- tickets: redmine:#32343 (implements)...` as a task header field. However:
  1. In `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py:54-67`, `OPTIONAL_EXTENSION_FIELDS` is defined as:
     `("profile", "verification-mode", "verifier", "size", "kind", "labels", "branch", "worktree", "run-id", "use-cases", "use_cases", "short")`
     `tickets` is absent.
  2. In `tasks_engine.py:5776-5778`, `validate_emergent_tasks` checks that all keys belong to `ALL_ALLOWED_HEADER_FIELDS`. Any task file containing a `tickets:` header will be rejected by `ai-orch doctor` with `unknown header field(s): tickets`.
  3. `tasks/specs/task-and-state-model.md` §2.1–§2.2 enforces a closed set of 13 mandatory core headers and strict positioning for extension fields *immediately after* `handoff`. The spec must define the canonical sequence.
  4. In `tasks/specs/orchestration-broker-mcp.md` §3b (line 131), the broker tool `tasks.set` restricts `field` to:
     `field: priority|size|deps|kind|labels|short`
     `tickets` is missing from `tasks.set`.
  5. Microtask headers (`tasks/specs/task-and-state-model.md` §2.4) currently do not include `tickets`, meaning a small bug fix or chore microtask (`tasks/micro/T###`) cannot declare a ticket link.
- **Evidence:**
  - `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py:54-67`: `OPTIONAL_EXTENSION_FIELDS` tuple.
  - `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py:5772-5785`: Header validation in `doctor`.
  - `tasks/specs/task-and-state-model.md:36-68`: Core and extension header field grammar.
  - `tasks/specs/orchestration-broker-mcp.md:131`: `tasks.set` parameter schema.
- **Concrete Fix:**
  1. In `tasks_engine.py`:
     - Add `"tickets"` to `OPTIONAL_EXTENSION_FIELDS` (immediately after `"use-cases"` / `"use_cases"` and before `"short"`).
     - Add `"tickets"` to `MICRO_HEADER_FIELDS` in optional position.
     - Add parser/serializer support for `tickets` in `TaskNode` and `parse_task_headers`.
  2. In `tasks/specs/task-and-state-model.md` §2.2, document `tickets: comma-separated list of <tracker>:#<id> (<relation>) or -`.
  3. In `tasks/specs/orchestration-broker-mcp.md` §3b, update `tasks.set` argument definition to: `field: priority|size|deps|kind|labels|short|tickets`.

---

### 2. False API Assumption: Redmine REST API Lacks Native Idempotency Keys, Causing Duplicate Tickets on Partial Bulk Failures
- **Severity:** Blocker
- **Spec Section:** §5 (lines 77–92) & §6 (lines 93–97)
- **Problem:**
  Section 5 (lines 90–92) asserts:
  *"Writes are performed by the agent through the transport (MCP) only from an approved plan, with idempotency keys per change; the engine records what was applied."*
  This is a false technical assumption:
  1. Standard Redmine (Ruby on Rails) REST APIs **do not support HTTP `Idempotency-Key` headers**. POST `/issues.json` does not deduplicate requests.
  2. If a bulk creation plan (such as creating 57 tickets as in T111) is interrupted at item 15 due to a socket timeout, rate limit, or HTTP 504 gateway timeout, re-running `tracker apply PLAN` will re-execute the plan from the beginning unless an explicit transaction ledger exists. This will create duplicate issues on Redmine for items 1–14!
  3. Redmine issue creation is not transactional: there is no atomic multi-issue rollback endpoint.
- **Evidence:**
  - `tasks/specs/tracker-links.md:90-92`: Claim of idempotency keys in transport.
  - Redmine Official REST API Documentation (`/issues.json`).
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/porting-lr74/T111-newis-resources-inventory-and-migration/README.md:120-123`: The custom script `create_tickets.py` had to record created IDs in `.tmp/t111/created.json` to ensure re-run idempotency.
- **Concrete Fix:**
  Replace the reference to transport idempotency keys with an engine-level stateful execution protocol:
  1. **Execution Ledger**: For every plan `tasks/_tracker/<tracker>/plans/plan-<ts>.json`, maintain an execution ledger `plan-<ts>.applied.json` (or write status per operation directly into the plan file). The ledger records `(step_id, redmine_issue_id, timestamp)` immediately upon receiving an HTTP 201 response, before issuing the next HTTP request.
  2. **Pre-Creation Subject Deduplication**: Before executing any `create_issue` step in a plan, the adapter must perform a query:
     `GET /issues.json?project_id=P&parent_id=C&status_id=*`
     If an issue with the identical subject already exists under that parent container, record its ID in the ledger and link it instead of issuing a duplicate POST.
  3. **Resume on Partial Failure**: If `tracker apply` aborts, running `tracker apply` again must resume from the first unapplied step in the ledger.

---

### 3. Destructive Inconsistency: `expand` and `collapse` Lifecycle Corrupts Tracker Projections and Orphans External Tickets
- **Severity:** Blocker
- **Spec Section:** §4 (lines 60–69)
- **Problem:**
  Section 4 specifies:
  *"Granularity follows how the work was opened... an item that exists in the task tree as its own unit (an initiative, an emergent task, a plan task expanded into a folder) maps to an issue; an item that is a line inside its parent (an inline plan task, a microtask, a checklist step) maps to a checklist line in its parent's issue. tasks expand / collapse therefore also change the projection..."*
  This produces two destructive failure modes:
  1. **The Collapse Deletion Trap**:
     In `tasks_engine.py:3060-3120`, `collapse_node` physically deletes the child folder and `README.md`, replacing it with an inline bullet in the parent's `plan.md` or `README.md`.
     If an expanded task already had an associated Redmine issue created during `mirror` or `map` mode:
     - Redmine issues cannot and should not be deleted (deleting destroys audit history and is typically blocked by permissions).
     - `collapse_node` wipes `README.md` and its `tickets:` header, completely severing the link in the local repository.
     - The Redmine issue becomes an unreferenced, zombie ticket in Redmine.
     - When `tracker plan` runs next, the parent issue's description block will show the item as a checklist line, while the orphaned Redmine issue remains open and unmaintained.
  2. **The Expand Split**:
     When an inline task (previously projected as a checklist line `* [ ] 01.1 Task`) is expanded into a folder via `expand_node`, the engine must promote the checklist item into a standalone issue. If the parent issue description is not reconciled, the task is tracked twice: once as an independent issue and once as an obsolete checklist item in the parent issue.
- **Evidence:**
  - `tasks/specs/tracker-links.md:62-66`: Expand/collapse alters projection.
  - `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py:3060-3120`: `collapse_node` removes child `README.md`.
- **Concrete Fix:**
  1. In `tasks_engine.py:collapse_node`:
     - Inspect whether the node being collapsed (or any of its descendants) has a `tickets:` header.
     - If tickets exist, mandate that `collapse` preserves the ticket reference in the collapsed inline block:
       `### 02.1 - Task Title\n- **Tickets:** redmine:#NNNNN (implements)\n...`
     - Do not drop ticket associations on collapse.
  2. In `tracker-sync`:
     - If an item was previously represented as a checklist item in parent `#P` and is now expanded into its own issue `#C`, the projection planner must generate a plan that:
       a) Creates child issue `#C` under parent `#P`.
       b) Replaces the checklist line in parent `#P`'s description with a reference link: `* [ ] [[#C]] Task Title`.
     - If a task with an issue is collapsed, the plan must never attempt HTTP `DELETE /issues/{id}.json`. It should append a note to issue `#C` stating the task was collapsed into `#P`, and update `#P`'s description checklist to reference `#C`.

---

### 4. Bulk Creation 422 Rejection: Missing Mandatory Tracker Fields (Categories, Assignees, Target Versions) in Mode Specifications
- **Severity:** Major
- **Spec Section:** §3 (lines 46–58) & §4 (lines 74–76)
- **Problem:**
  In `map` and `mirror` modes, the engine proposes creating issues for unmatched tasks under a container.
  However, in Redmine (specifically the D4Science instance), creating an issue under a project frequently enforces mandatory fields:
  1. **Issue Category**: In Portal-Revamping (#147), every created ticket must have a category (e.g. `category_id` for "Gateway (Liferay, mostly)" or "Smartgears Services"). See `T032/redmine_tickets_2026-09-30.md:3-5`.
  2. **Target Version**: Mandatory in certain workflow transitions or trackers (e.g. "To Be Planned").
  3. **Assignee**: As documented in `T032/redmine_tickets_2026-09-30.md:4-5`: *"Redmine requires an assignee: every ticket is assigned to Alfredo Oliviero, to be reassigned."*
  4. **Tracker Type**: Must match an allowed tracker in that project (e.g. Activity vs Task).
  Draft 1's `[tracker.redmine]` config only specifies `project` and `container`. If `mirror` or `map` attempts to create issues using only `subject`, `description`, `project_id`, and `parent_issue_id`, Redmine will reject the POST requests with `422 Unprocessable Entity` ("Category cannot be blank", "Target version cannot be blank").
- **Evidence:**
  - `tasks/specs/tracker-links.md:50-58`: `[tracker.redmine]` configuration definition.
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/release-push/T032-redmine-status-sync/redmine_tickets_2026-09-30.md:3-5`: Category, target version, and assignee requirements.
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/porting-lr74/T111-newis-resources-inventory-and-migration/README.md:51-53`: Tracker types and project metadata.
- **Concrete Fix:**
  1. Expand the `[tracker.redmine]` configuration schema to support project defaults and profile mappings:
     ```toml
     [tracker.redmine.defaults]
     tracker = "Task"
     category = "Gateway (Liferay, mostly)"
     target_version = "To Be Planned"
     assignee = "current_user" # resolves via /users/current.json
     ```
  2. Mandate that before generating a creation plan, `tracker plan` queries `/projects/{project_id}.json?include=trackers,issue_categories` and `/users/current.json` to pre-validate that all mandatory fields are supplied.

---

### 5. Specification Gap on Items Table Hierarchy (1 Row to Multi-Ticket Mapping in Practice vs 1 Row to 1 Ticket Assumption)
- **Severity:** Major
- **Spec Section:** §4 (lines 66–69)
- **Problem:**
  Section 4 specifies:
  *"A task that enumerates work units in a table (components, artifacts, resources, as in T111) may declare the table as an item set (items: table "Components" key "artifact"): each row maps to an issue (or a line) by the same rule, with the row's ticket id kept in a Ticket column."*
  This single-ticket assumption breaks against the real-world practice of T111:
  1. In T111 (`README.md:120-153`), the component inventory table does **not** map 1 row to 1 ticket. Each component row mapped to **up to three distinct tickets across two hierarchy levels**:
     - Generic component ticket (Level 1, e.g. `#32504`).
     - 6.2 sub-ticket (Level 2, e.g. `#32505`).
     - 7.4 sub-ticket (Level 2, e.g. `#32506`).
     Moreover, some components had no 6.2 ticket (dismissed) or no 7.4 ticket (no module planned).
  2. If `items: table` only supports a single `Ticket` column, it cannot represent multi-level ticket structures for work units.
  3. The specification does not clarify where `items:` is placed (task header vs body directive) or how `tracker apply` modifies markdown tables safely without breaking markdown table alignment or dropping adjacent columns.
- **Evidence:**
  - `tasks/specs/tracker-links.md:66-69`: Single `Ticket` column assumption.
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/porting-lr74/T111-newis-resources-inventory-and-migration/README.md:57-63, 120-153`: 3-level ticket structure per component.
- **Concrete Fix:**
  1. Expand `items: table` definition to support multiple ticket roles across columns:
     `items: table "Components" key "artifact" tickets ["Ticket", "6.2 Ticket", "7.4 Ticket"]`
     or with role mappings:
     `tickets_columns: { generic: "Ticket", jdk8: "6.2 Ticket", jdk17: "7.4 Ticket" }`
  2. Clearly define the syntax and placement of `items:`. If placed in task headers, add `items` to `OPTIONAL_EXTENSION_FIELDS` in `tasks_engine.py`. If placed in task bodies, specify a structured block format:
     ```markdown
     <!-- ai-orch:items table="Components" key="artifact" ticket_col="Ticket" -->
     ```
  3. Specify that table updates must use AST-based table rewriting (e.g. via markdown table parser) rather than crude string regexes to avoid corrupting custom table formatting.

---

### 6. Silent Failure Trap: API Key Resolution via `env:` Fails in GUI Environments (VS Code / Claude Desktop)
- **Severity:** Major
- **Spec Section:** §3 (lines 50–58)
- **Problem:**
  Section 3 illustrates tracker configuration with:
  `key_source = "env:REDMINE_API_KEY" # or file:~/.config/gcube/redmine/api_key`
  This contradicts the hard-learned lesson documented in `gcube-redmine-assistant/SKILL.md` (lines 31–38):
  *"Do not read the API key from an environment variable. ${env.…} interpolation resolves to an empty string whenever the host application is launched outside a shell that exported it (for example VS Code started from Finder or the Dock). The server then starts, authenticates as anonymous and fails silently: requests come back 401/403 or partial, and the agent reasons over them as if they were data."*
  In Redmine, unauthenticated requests to public projects return HTTP 200 but filter out private issues and restricted fields. If an orchestrator or developer runs `tracker plan` inside VS Code or Claude Desktop with an unexported `REDMINE_API_KEY`:
  - The request succeeds anonymously with HTTP 200.
  - Private tickets disappear from view.
  - The engine assumes those tickets do not exist, concludes work is missing, and generates a plan proposing duplicate issues!
- **Evidence:**
  - `tasks/specs/tracker-links.md:53`: `env:REDMINE_API_KEY` listed as first configuration option.
  - `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/d4science-ecosystem-tools/skills/gcube-redmine-assistant/SKILL.md:31-38`: Detailed analysis of the silent empty-env failure mode.
- **Concrete Fix:**
  1. Change the configuration default to prefer local config files:
     `key_source = "file:~/.config/gcube/redmine/api_key"` (or `~/.config/ai-orchestration/trackers/redmine.key`).
  2. Implement an indispensable **Pre-Flight Authentication Guard**:
     Before executing any query or generating any plan/snapshot, the engine MUST call `GET /users/current.json`.
     If the call returns HTTP 401, or if the user object represents an anonymous user (`id == null` or `login == ""`), the engine must abort immediately with a hard error:
     `TrackerAuthError: Redmine API key is missing or unauthenticated. Anonymous queries are strictly forbidden to prevent partial-visibility corruption.`

---

### 7. Closed-Issue Blindness: Missing `status_id=*` Filter Causes Incomplete Trees and Ghost Issue Recreation
- **Severity:** Major
- **Spec Section:** §4 (lines 74–76) & §5 (lines 88–89)
- **Problem:**
  Section 4 (§4 `map` mode) requires:
  *"read the container's subtree, match its issues to the tasks/items... and propose creating issues for the unmatched tasks under the container"*.
  Section 5 (§5 Snapshot) requires:
  *"a deterministic JSON snapshot of the linked issues... so re-alignment is a git diff"*.
  Neither section mentions passing `status_id=*` during issue queries.
  In Redmine REST API, `GET /issues.json` (and `GET /projects/{id}/issues.json`) **hides closed issues by default**.
  As documented in `gcube-redmine-assistant` (lines 66–68):
  *"issues.json?issue_id=a,b,c hides closed issues by default. Add &status_id=*, otherwise part of the tree disappears with no warning and the analysis looks complete."*
  If `status_id=*` is omitted:
  1. Completed sub-issues in the container tree will be invisible to `map` mode.
  2. `map` mode will identify previously completed tasks as "unmatched tasks", proposing to recreate tickets that are already closed!
  3. Snapshots will drop closed tickets, creating noisy diffs whenever an issue transitions to closed.
- **Evidence:**
  - `tasks/specs/tracker-links.md:74-76, 88-89`: Omits query parameter requirements.
  - `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/d4science-ecosystem-tools/skills/gcube-redmine-assistant/SKILL.md:66-68`: Specific pitfall of closed issues vanishing.
- **Concrete Fix:**
  Explicitly mandate in §4 and §5 that all queries fetching issues by container, list, or project MUST include `status_id=*` and `include=children,relations,journals`.

---

### 8. Silent Field Clearing on Save: Core Fields Wiped on Full Issue PUTs (The T111 `start_date` Loss)
- **Severity:** Major
- **Spec Section:** §5 (lines 85–86)
- **Problem:**
  Section 5 line 85 states:
  *"Field safety: before a save, the engine reads the tracker's enabled core fields and never sends a field the tracker would clear; after the save it reads back and reports differences (the T111 start_date loss)."*
  This specification is problematic in two ways:
  1. In standard Redmine REST APIs, the `/trackers.json` endpoint **does not expose `enabled_core_fields` to non-admin users**. An ordinary developer's API key cannot inspect which core fields are enabled or disabled for a tracker.
  2. If an adapter constructs a full issue representation and issues a `PUT /issues/{id}.json` containing fields that Redmine considers disabled for that tracker, Redmine's ActiveRecord model callback silently sets those fields to `NULL` in the database. In T111 (README line 103), this wiped `start_date` across all 8 existing tickets.
- **Evidence:**
  - `tasks/specs/tracker-links.md:85-86`: Relying on API query of enabled core fields.
  - `/Users/Alfredo/works/gcube/porting_liferay/tasks/porting-lr74/T111-newis-resources-inventory-and-migration/README.md:103`: Description of silent `start_date` loss during ticket updates.
- **Concrete Fix:**
  1. **Strict Minimal Patching (Delta Only)**: Enforce at the adapter level that `PUT /issues/{id}.json` payloads must ONLY contain the fields explicitly targeted for update (e.g. `{"issue": {"description": "...", "notes": "..."}}`). The adapter must NEVER echo back untouched fields (`start_date`, `due_date`, `done_ratio`, `estimated_hours`, `assigned_to_id`).
  2. **Profile Whitelist/Blacklist**: The D4Science profile must define static metadata of known disabled fields for common trackers (e.g. `Task` has disabled `start_date`).
  3. **Diff Verification**: Before and after PUT, read back the issue. If any unmentioned field changed or was cleared, emit an immediate warning in the report and log it as a sync alert.

---

### 9. Relation Semantics: Single-Parent Constraints and Unmapped Task Dependencies
- **Severity:** Major
- **Spec Section:** §2 (lines 38–40) & §4 (lines 72–76)
- **Problem:**
  1. **Multiple `under` Relations**: In §2 line 34, the example shows:
     `- tickets: redmine:#32343 (implements), redmine:#32197 (under), redmine:#30584 (cites)`
     In Redmine, an issue supports only a **single parent issue** (`parent_issue_id`). If a task specifies two `under` relations, or if an initiative has `under: #A` while a child task has `under: #B`, the Redmine hierarchy cannot represent multiple parents.
  2. **Mapping Task Dependencies to Issue Relations**:
     When Task B `depends-on: Task A`, and both have mapped Redmine tickets, how does the engine link them on Redmine?
     In Redmine, issue relation types are: `relates`, `duplicates`, `duplicated`, `blocks`, `blocked`, `precedes`, `follows`.
     As emphasized in `gcube-redmine-assistant` (lines 176–179), `precedes`/`follows` are hazardous scheduling constraints that shift dates and must be avoided. However, the spec does not state whether `depends-on` should generate `relates`, `blocks`, or nothing at all.
  3. **Behavioral Divergence of `implements` vs `updates`**:
     Section 4 line 73 groups them together: *"for each implements/updates link: update the issue's description block... with the task's state, checklist and done_ratio... add a note on state transitions"*.
     This blurs their semantic distinction: if a task only `updates` a ticket (e.g. reporting progress from a sub-component), should it overwrite the entire ticket description and recompute `done_ratio`, or only append progress journal notes?
- **Evidence:**
  - `tasks/specs/tracker-links.md:38-40, 73`: Definitions of relations.
  - `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/d4science-ecosystem-tools/skills/gcube-redmine-assistant/SKILL.md:176-179`: Scheduling dangers of `precedes`/`follows`.
- **Concrete Fix:**
  1. Enforce that a task may have at most **one** `under` ticket. If multiple containers are cited, the first is assigned as `parent_issue_id` and the remainder must use `cites` or generate `relates` links.
  2. Specify issue dependency mapping: When syncing tasks where Task B depends on Task A, the engine proposes an issue relation of type `relates` (or `blocks`, if configured by profile), and explicitly blacklists `precedes` and `follows`.
  3. Differentiate `implements` vs `updates`:
     - `implements`: Primary owner. Manages the description marker block, recomputes `done_ratio`, and manages status transition proposals.
     - `updates`: Secondary reporter. Leaves description and status unchanged; posts journal notes at milestone transitions (e.g. delivered/done).

---

### 10. Multi-Task Marker Collisions in Shared Ticket Descriptions
- **Severity:** Minor
- **Spec Section:** §4 (lines 72–73)
- **Problem:**
  Section 4 specifies that `link` mode updates the issue's description block between generated markers.
  Because the link model is n:m, multiple tasks in the repository may link to the same issue with `implements` (for example, in `porting_liferay`, multiple porting tasks contributed to `#32180` layout conversion or `#32184` repository split).
  If multiple tasks share a single marker pair (`<!-- ai-orch:begin -->...<!-- ai-orch:end -->`), updating Task A will overwrite the checklist and progress block generated by Task B!
- **Evidence:**
  - `tasks/specs/tracker-links.md:41, 73`: n:m links and description marker blocks.
- **Concrete Fix:**
  Scope description marker blocks by task ID:
  `<!-- ai-orch:begin task=T032 -->` ... `<!-- ai-orch:end task=T032 -->`
  Alternatively, when multiple tasks implement the same issue, the engine must merge their projections into a single consolidated description section sorted by task ID.

---

### 11. Notification Noise and Rate Limiting
- **Severity:** Minor
- **Spec Section:** §4 (lines 72–76) & §5 (lines 78–82)
- **Problem:**
  Redmine dispatches notification emails to assignees, authors, and project watchers on every write (issue creation, issue update, note addition).
  If an automated agent triggers `tracker apply` frequently during microtask transitions or updates descriptions on every commit, dozens of email notifications will flood team members' inboxes. Redmine's standard REST API does not provide a parameter for regular users to suppress notifications (`no_notification`).
- **Evidence:**
  - `tasks/specs/tracker-links.md:73`: Automatic note addition on transitions.
  - `/Users/Alfredo/works/ai-coding-tools/gcube-ai-toolkit/plugins/d4science-ecosystem-tools/skills/gcube-redmine-assistant/SKILL.md:88, 98`: *"The tracker is read by people. Every write is a notification. Batch at natural boundaries..."*
- **Concrete Fix:**
  1. Clarify in §4 and §5 that `tracker apply` is an explicit, batched operation intended for milestone boundaries (e.g. pull request delivery, milestone completion, release readiness), not a continuous background streaming hook.
  2. Mandate that within a single `tracker apply` execution, multiple transitions or subtask changes affecting the same issue MUST be aggregated into a single HTTP update containing one consolidated journal note.

---

### 12. Undefined Profile Architecture and Loading Mechanism
- **Severity:** Minor
- **Spec Section:** §1 (lines 20–26) & §3 (line 57)
- **Problem:**
  Section 1 describes `gcube-redmine-assistant` as becoming the "D4Science profile of `tracker-sync`". Section 3 lists `profile = "d4science"`.
  However, the spec does not define what a "profile" actually is in code:
  - Is it a TOML file under `plugins/shared/profiles/`?
  - A Python class extending a base `TrackerProfile`?
  - A set of skill instructions?
  Without a formal profile interface, developers cannot know how to define custom tracker profiles (e.g. for GitHub Issues, Jira, or a generic vanilla Redmine instance).
- **Evidence:**
  - `tasks/specs/tracker-links.md:23-26, 57`: Mention of profiles without interface definition.
- **Concrete Fix:**
  Formally specify the Profile schema:
  A profile is defined by a declarative configuration file (`profiles/<name>.toml`) supplying:
  1. Default field mappings (`tracker_id`, `category_id`, `version_id`).
  2. Allowed and disabled core fields per tracker.
  3. Status mappings (`open`, `in_progress`, `delivered`, `done` -> integer status IDs).
  4. Checklist formatting conventions (e.g. `* [.]` for in-progress).
  Coupled with an optional Python hook class for custom template rendering or validation.

---

## What is Sound in Draft 1

Draft 1 gets several foundational architectural decisions completely right:

1. **Repository as Ground Truth**: Adopting the philosophy from `gcube-redmine-assistant` that the repository is the primary source of truth, and the tracker is merely a derived projection, is the only sustainable way to prevent tracker rot.
2. **Strict Propose-Then-Apply**: Mandating that every tracker modification must first be computed as a deterministic, human-readable plan (`plan-<ts>.json` and readable twin) before application ensures human oversight and eliminates hallucinated tracker vandalism.
3. **Hybrid Granularity Rule**: Basing projection granularity on how work was opened (initiatives/tasks as issues; subtasks/checklist items as description checklist text) solves the impedance mismatch between git commits and tracker tickets. Granularity inside descriptions is free; granularity as tracker objects is costly.
4. **Deterministic Snapshot Diffing**: Storing a committed `snapshot.json` (sorted keys, stripped generation timestamps) transforms tracker re-alignment from an expensive, open-ended re-analysis into a clean `git diff`.
5. **Ownership Boundary Enforcement**: Restricting issue edits to tickets authored by or assigned to the user, and allowing only notes on third-party tickets, is an essential safety guard for multi-user team trackers.
6. **First Examples Approval**: Adopting the T111 practice of having the human operator inspect the first container and first pair of child tickets before executing bulk ticket creation provides an indispensable practical safety net.

---

## Evaluation of the Four Owner Cases & Porting Practice

| Case / Practice Requirement | Covered in Draft 1? | Evaluation & Specific Gaps |
| :--- | :--- | :--- |
| **Case 1: Update a linked issue linking it to the task** | Yes (`link` mode) | Well covered. Updates description between markers and posts transition notes. Needs marker scoping per task to prevent collisions (Finding 10). |
| **Case 2: Open sub-items for managed tasks** | Yes (`mirror` mode) | Conceptually covered, but will fail with HTTP 422 if project requires mandatory categories, assignees, or target versions (Finding 4). Needs single-parent constraint on `under` (Finding 9). |
| **Case 3: Map tasks onto existing tickets of an activity & open missing** | Yes (`map` mode) | Conceptually sound, but omitting `status_id=*` will make closed tickets invisible and trigger duplicate creation proposals (Finding 7). |
| **Case 4: No link at all** | Yes (`none` mode) | Completely covered. Passive display of `cites` links without tracker writes. |
| **Practice: Issues per component/artifact** | Yes | Matches porting_liferay conventions (e.g. T032, T010). |
| **Practice: T111 Three Levels** | Partial | T111 produced a 3-level ticket hierarchy (Activity -> Component -> 6.2/7.4 line). The single-column `items: table` assumption in Draft 1 cannot represent this structure without extension (Finding 5). |
| **Practice: Checklists in area tickets** | Yes | Accurately models the in-description checklist convention (`* [x]`, `* [.]`, `* [ ]`) used in Dave and porting_liferay. |

---

## Review and Recommendations on Open Questions

### Open Question Q-a
> *"Should `link` mode change issue **status** automatically when the task is `done` (with evidence), or only add a note and propose the status change?"*

- **Recommendation:** **Do not change status automatically by default; propose status changes in the plan and append a note with evidence.**
- **Rationale:**
  1. In multi-user ecosystems (and D4Science specifically), issue status transitions trigger automated Jenkins pipelines, notification blasts, or handoffs to QA/release coordinators.
  2. As demonstrated in `T010-release-tickets-17579.md:29-31`, release tickets for components remain in status `New` as long as their code is in `SNAPSHOT` state, even if development tasks are fully completed and verified locally. Closing or moving the ticket to `Resolved` prematurely misrepresents release readiness.
  3. Redmine's workflow permissions frequently forbid developers from transitioning issues directly to `Closed` (often restricted to project managers or QA). Attempting an automatic transition will cause `422 Unprocessable Entity` or `403 Forbidden`.
  4. The engine should propose the status change in the generated `plan-<ts>.json` and post a Markdown note citing the commit/verification evidence. An explicit configuration option (`auto_status = true` in `[tracker.redmine]` or `--auto-status` CLI flag) can be provided for users who explicitly opt in.

### Open Question Q-b
> *"Where should the plans and snapshots live: in the project (`tasks/_tracker/`, versioned, as the skill recommends) or in `.ai-orchestration/` (not versioned)?"*

- **Recommendation:** **Adopt a hybrid model: Snapshots and Mappings are versioned in `tasks/_tracker/`; execution plans and ledgers are ephemeral/git-ignored.**
- **Rationale:**
  1. **Snapshots (`tasks/_tracker/<tracker>/snapshot.json` and twin `snapshot.md`) MUST be committed and versioned in the project.** The core value of the method is that re-alignment across sessions, worktrees, and developers is a simple `git diff`. If snapshots live in `.ai-orchestration/` (git-ignored), every fresh clone or worktree loses the snapshot baseline and is forced to perform an expensive full fetch and re-analysis.
  2. **Mapping declarations (`tasks/_tracker/<tracker>/mapping.md`) MUST be committed and versioned.** The mapping defines the semantic alignment between repository code/tasks and external issues, which is durable project documentation.
  3. **Execution Plans (`plan-<ts>.json`, `plan-<ts>.applied.json`) should live in `tasks/_tracker/<tracker>/plans/` and be git-ignored (or placed in `.tmp/tracker/`).** Transient execution plans are one-off execution artifacts. Committing every timestamped plan clutters git history with ephemeral noise. Once a plan is applied, its permanent state is already captured by the modified `tickets:` headers in task files and the updated `snapshot.json`.
