# Tracker links: tasks and Redmine issues

- status: draft 2 (2026-10-18), v1 scope after one review round (Codex and Gemini,
  `../_reviews/2026-10-18-tracker-links-review-{codex,gemini}.md`, cited as Cn and Gn).
- owner request (2026-10-18): tasks can reference a ticket; a project or a task may have an associated Redmine activity
  or issue. Cases: (1) update an issue, linking it to the task; (2) open sub-activities and items linked to the managed
  tasks; (3) map the tasks onto the existing tickets of an activity and open the missing ones; (4) no link at all.
  Granularity: **hybrid, following the granularity at which the work was opened**.
- evidence: the method of `gcube-redmine-assistant` (repository is the truth, the tracker a projection; propose then
  apply; ownership boundary; checklist convention; computed `done_ratio`; evolve, don't reopen; `relates`, never
  `precedes`/`follows`; deterministic snapshot); the practice in `~/works/gcube/porting_liferay` (tasks cite issues n:m;
  issues follow work units such as components and Maven artifacts; T111: Activity → one ticket per component → one
  sub-ticket per line 6.2/7.4 when the component exists there; first examples approved before bulk creation; a save
  through the API cleared a field disabled for that tracker).

## 1. Layers

- **ai-orchestration core:** typed links in the task format; projection, validation, canonical plans, checkpoints and
  receipts in the engine; a generic skill `tracker-sync` (template + per-tool bindings) that tells agents how to
  propose matches and texts and how to drive the engine.
- **Transport:** `mcp-redmine` (MCP), `redmine-rest-helper` as fallback; the engine calls a narrow adapter only to
  execute an approved, exact plan.
- **D4Science profile:** `gcube-redmine-assistant` becomes the profile of `tracker-sync` (traps, field ids,
  required custom fields, ticket templates, release-ticket conventions, credentials from a file). Prerequisite: its
  three diverging copies (toolkit, `porting_liferay/.claude`, `porting_liferay/.kilo`) are reconciled into the toolkit
  and `/redmine` stops pointing at the retired `d4science-redmine-helper`.
- **v1 is Redmine only** (C simpler v1). The model names the tracker in every reference so other trackers can follow.

## 2. Division of work (C11)

| Who | Does |
| --- | --- |
| agent (with the profile) | proposes matches between tasks/items and issues, writes subjects/descriptions/notes, explains uncertain pairs |
| engine | parses and validates links, assigns and preserves projections, renders generated blocks and checklists, computes `done_ratio`, builds a canonical plan with a hash, preflights it, records checkpoints and receipts |
| owner | approves a plan (or its first examples for a bulk creation), decides status changes |
| adapter | executes the approved plan operation by operation, nothing else |

## 3. Links on task nodes (C10, G1)

- Links live on logical task nodes: initiatives, emergent tasks, plan tasks (`- tickets: …` in headers, `**Tickets:**`
  in plan-task status lines). Project and workspace defaults are configuration (§5), not headers.
- Serialisation: comma-separated `redmine:#<id> (<relation>)`, sorted by relation then id; the engine rewrites the
  field canonically.
- Relations:
  - `implements`: primary owner of the issue's generated block, its checklist and `done_ratio`; may propose status
    changes;
  - `updates`: posts notes at state boundaries; never touches description or status (G9);
  - `verifies`: checks someone else's work on the issue; notes only;
  - `under`: the container this node belongs to; **at most one per node** (Redmine issues have one parent, G9);
    inherited by children unless overridden;
  - `cites`: context only, never read for sync and never written.
- A node's `depends-on` is projected, when both sides have issues, as a proposed `relates`; `precedes`/`follows` are
  never created (G9, method).
- Free-text `#NNNNN` in existing files is offered as structured links by `tasks tickets adopt --preview`; nothing is
  rewritten silently.
- The engine schema (`OPTIONAL_EXTENSION_FIELDS`) and the broker contract (`orchestration-broker-mcp.md` §3b:
  `tasks.show`/`tasks.list` gain `tickets`, `tasks.set` gains `field=tickets`) are amended in the same change (C10).

## 4. Projection: the hybrid granularity rule, made stable (C1, C2, G3)

- Every linked or managed node has a **projection** `issue | line | none`, assigned **once**, when it is first mapped,
  and stored with the node (`projection:` header / `**Projection:**`). `expand`, `collapse`, archive and moves
  preserve it; they never create, close or demote issues. Changing a projection is an explicit command with a plan.
- **Initial default (the hybrid rule, owner decision):** the projection follows how the work was opened:
  - a node opened as a unit of work of its own (an initiative, an emergent task, or an item of a declared item set) →
    `issue`;
  - a node opened as a step inside its parent (a plan task, a microtask) → `line` in the parent's issue;
  - the D4Science profile keeps the method's guidance in the default: a sub-issue under an `issue` node only when the
    assignee or the tracker type differs, otherwise `line`; the owner overrides per node or per initiative when the
    work was deliberately opened finer (as in T111).
- **Item sets (C7, G5)** for work units that are table rows (components, artifacts, resources):

  ```text
  <!-- ai-orch:items table="Components" key="artifact" -->
  ```

  - placed in the task body, right above the table; `key` names a column with unique, immutable values (the identity;
    never the subject text);
  - per-row projection: `issues`, `lines`, or `issues-when:<column>=<value>`;
  - **derived child tickets** per row (T111's 6.2/7.4 lines): `children="6.2 line:col=6.2 present;7.4 line:col=7.4
    present"`, each with its own ticket column (`Ticket`, `Ticket 6.2`, `Ticket 7.4`);
  - the engine rewrites only the ticket columns of the rows it created, with a table-aware parser.

## 5. Configuration

```toml
[tracker.redmine]
url = "https://support.d4science.org"
key_file = "~/.config/gcube/redmine/api_key"   # file first (env fails for GUI-launched tools, G6); never in the repo
project = "<redmine project identifier>"
container = 29767        # optional default `under` for this project or initiative
mode = "none"            # none | link | reconcile   (per initiative or task override)
profile = "d4science"
notify_threshold = 10    # plans with more writes need a second approval (C8)
```

## 6. Modes (C3): truth table

| Mode | Reads | Proposed writes | Persisted after apply | Later syncs | Unmatched |
| --- | --- | --- | --- | --- | --- |
| `none` | nothing | nothing | – | nothing | – |
| `link` (case 1) | the linked issues (with journals, children, relations) | for `implements`: one PUT per issue with the generated block + `done_ratio` + one note if the node crossed a state boundary; for `updates`/`verifies`: one note at a boundary | receipts, snapshot | same, only for changed nodes | – |
| `reconcile` (cases 2 and 3) | the container's whole subtree (`status_id=*`, recursive, journals) | matches proposed by the agent (explicit links first, then proposals with confidence); for every node or row with projection `issue` and no issue: a create under the container (subject, tracker, template, parent, required fields); then the `link` writes | accepted matches become `tickets:` links; created ids written back to the node or row | behaves as `link` | three sections in the plan, never auto-resolved: issues with no task, tasks with no issue (when creation is declined), uncertain pairs |

Case 2 ("open sub-activities and items for the managed tasks") is `reconcile` on a container with creation enabled.
Case 3 ("map onto existing tickets and open the missing") is `reconcile` with the agent's matching.
**Status changes are only proposed in v1** (C12): the plan shows the transition and the evidence (a delivered/done
node, a commit); the owner decides. Closed issues are frozen; resumed work gets a new issue citing the old one with
`relates`.

## 7. Safety

- **Preflight before any write (C4, C5, G4, G7, G8):** read with `status_id=*`, recursive children, `include=
  children,relations,journals`; the current user (ownership boundary: edit own or assigned issues, notes only on
  others'); the project's trackers, categories and versions; the profile's required custom fields and assignee rules;
  the allowed status transitions for this issue and user; **non-empty fields that are disabled for the issue's
  tracker** — a PUT that would clear them is blocked, or needs an explicit approval naming the loss. A 422 is a plan
  defect, not a retry.
- **One PUT per issue per apply** (description block, `done_ratio`, note together), expected notification count
  shown in the plan, second approval above `notify_threshold` (C8).
- **Generated blocks per node (G10):** `<!-- ai-orch:begin <node-qualified-id> -->…<!-- ai-orch:end … -->`, so several
  `implements` nodes on one issue never overwrite each other; text outside the blocks is never changed.
- **No idempotency in Redmine (C6, G2):** every operation has a deterministic local op id; creates embed a provenance
  marker (`ai-orch-op: <op id>`) in the description; after each operation the engine checkpoints
  `pending | applied | unknown | failed`; an `unknown` create is reconciled by searching the marker before any retry;
  before each update the issue's `updated_on` (or content hash) must match the plan; the run stops at the first failure
  and resumes the remaining operations later, without rollback.
- **Approval of bulk creation:** the plan marks the first container and the first parent/child pair as samples; the
  owner approves them, they are applied and read back, then the rest of the plan is approved.

## 8. Where state lives (C9; decides the former open question Q-b)

- **Versioned, sanitised:** `tasks/_tracker/redmine/` — approved plans, receipts, the link mapping, and an allowlisted
  deterministic snapshot (ids, subjects, status, parent, assignee login, `done_ratio`, our generated blocks), with a
  readable twin, so re-alignment is a `git diff`.
- **Not versioned:** raw API responses and journals in `.ai-orchestration/tracker-cache/` (git-excluded); never
  credentials or secret-bearing values anywhere in plans or logs.

## 9. Commands and broker

- `ai-orch tasks tickets link|unlink ID REF --relation R`, `tickets list`, `tickets adopt --preview`,
  `tasks projection set ID issue|line|none`
- `ai-orch tracker snapshot`, `tracker plan --mode link|reconcile [--scope ID] [--create]`, `tracker apply PLAN
  --expect-hash H [--samples-only]`, `tracker resume RUN`, `tracker status`
- Broker: `tickets` in `tasks.show`/`tasks.list`, `tasks.set field=tickets`, `tracker.plan` (read-only); `apply` stays
  owner-facing (UI/CLI), like the broker's other owner-facing actions.

## 10. Open question for the owner

- Q-a: in v1 status changes are only proposed. Should a later version apply them automatically when the evidence is
  unambiguous (a `done` node with a merged commit), or always stay a proposal?
