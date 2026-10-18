# Tracker links: tasks and external tickets (Redmine first)

- status: draft 1 (2026-10-18), to be reviewed (Codex, Gemini) before the plan.
- owner request (2026-10-18): tasks can reference a ticket. A project or a single task may have an associated Redmine
  activity or issue. Cases: update an issue linking it to the task; open sub-activities and items linked to the managed
  tasks; map tasks onto the existing tickets of an activity and open the missing ones; or no link at all. Decide
  whether to evolve the existing Redmine skills or write new ones for ai-orchestration. Granularity (owner): **hybrid,
  following the granularity at which the tasks were opened**.
- evidence: the method in `gcube-ai-toolkit/.../gcube-redmine-assistant/SKILL.md` (tracker as a derived projection,
  propose then apply, ownership boundary, checklists, evolve-don't-reopen, `relates` not `precedes`, deterministic
  snapshot); practice in `~/works/gcube/porting_liferay` (survey 2026-10-18): tasks cite issues n:m as free text
  (`#NNNNN` in `sources:`, titles, bodies); issues follow natural work units (one per component, one per Maven
  artifact, three levels Activity → component → line in T111), not task files; first examples shown to the owner
  before bulk creation; Redmine clears core fields disabled for a tracker when saving through the API.

## 1. Decision on skills

Two layers, no rewrite of the transport:

- **Core (ai-orchestration):** a tracker-agnostic link model in the task format, deterministic projection and planning
  in the engine, and a generic skill `tracker-sync` (template + bindings, like `orchestration-workflow`).
- **Transport and house rules:** `mcp-redmine` (MCP) with `redmine-rest-helper` as fallback for the calls;
  `gcube-redmine-assistant` becomes the **D4Science profile** of `tracker-sync` (its traps, field ids, templates,
  release-ticket conventions). Before that, its three diverging copies (toolkit, `porting_liferay/.claude`,
  `porting_liferay/.kilo`) are reconciled into the toolkit, and `/redmine` stops pointing at the retired
  `d4science-redmine-helper`.

## 2. Link model (n:m, typed)

- Any task, plan task, initiative, project or workspace may carry `tickets:` (header field; plan tasks use the bold
  form `**Tickets:**`):

  ```text
  - tickets: redmine:#32343 (implements), redmine:#32197 (under), redmine:#30584 (cites)
  ```

- Reference grammar: `<tracker>:#<id>` with `<tracker>` a configured tracker name (`redmine`, later `gitea`, `github`).
- Relations: `implements` (the task does the issue's work), `updates` (the task reports progress on it), `verifies`
  (the task checks someone else's work on it), `under` (the issue is the container this work belongs to), `cites`
  (context only; never written to).
- The same issue may be linked from many tasks and a task may link many issues. Free-text `#NNNNN` in existing
  files is detected by `tasks tickets adopt --preview` and offered as structured links (never silently rewritten).
- Engine: parse, validate (known tracker, numeric id, known relation), expose in JSON (`tickets: [{tracker, id,
  relation}]`), show in UI/VS Code with links, include in the broker contract (`tasks.show`, `tasks.set field=tickets`).

## 3. Tracker configuration

Per project (or workspace, inherited by its projects):

```toml
[tracker.redmine]
url = "https://support.d4science.org"
key_source = "env:REDMINE_API_KEY"          # or file:~/.config/gcube/redmine/api_key; never stored in the repo
project = "<redmine project identifier>"
container = 29767                          # optional default `under` activity for this project/initiative
mode = "none"                              # none | link | map | mirror (§4); per initiative/task override allowed
profile = "d4science"                      # house rules: field ids, templates, owner rules
```

## 4. Modes and the hybrid granularity rule

**Granularity follows how the work was opened** (owner decision): an item that exists in the task tree as its own unit
(an initiative, an emergent task, a plan task expanded into a folder) maps to **an issue**; an item that is a line
inside its parent (an inline plan task, a microtask, a checklist step) maps to **a checklist line** in its parent's
issue. `tasks expand` / `collapse` therefore also change the projection; the plan shows that before any write.
A task that enumerates **work units** in a table (components, artifacts, resources, as in T111) may declare the table
as an item set (`items: table "Components" key "artifact"`): each row maps to an issue (or a line) by the same rule,
with the row's ticket id kept in a `Ticket` column.

| Mode | Effect (always as a proposed plan; nothing is written without approval) |
| --- | --- |
| `none` | no tracker interaction; `tickets: cites` links are still shown |
| `link` | for each `implements`/`updates` link: update the issue's description block (generated, between markers) with the task's state, checklist and `done_ratio` computed from the tree; add a note on state transitions at natural boundaries (delivered, done); never change status without evidence (a delivered/done task, a commit) |
| `map` | read the container's subtree, match its issues to the tasks/items (by explicit links first, then by subject similarity as **proposals** with confidence), list unmatched issues, unmatched tasks and uncertain pairs (the three sections the skill already requires), and propose creating issues for the unmatched tasks under the container |
| `mirror` | for every managed task/item that maps to an issue by the granularity rule and has none: propose creating it under the container, with subject, tracker, template and parent; then behave as `link` |

## 5. Safety and approval

- **Propose, then apply**, always: the engine writes a deterministic plan (`tasks/_tracker/<tracker>/plan-<ts>.json` +
  a readable twin) with every intended change (issue, field, current value, proposed value, exact text). The owner
  approves the plan or the **first examples** of a bulk creation (first container, first pair of children), as done
  in T111; the rest is applied only after that.
- **Ownership boundary** (from the skill): issues the owner authored or is assigned to may be edited; on others' issues
  only notes. Checked from fetched data before each batch.
- **Field safety:** before a save, the engine reads the tracker's enabled core fields and never sends a field the
  tracker would clear; after the save it reads back and reports differences (the T111 `start_date` loss).
- **No reopen, `relates` not `precedes`/`follows`, batching at natural boundaries**: as in the skill.
- **Snapshot:** a deterministic JSON snapshot of the linked issues (`tasks/_tracker/<tracker>/snapshot.json`, sorted,
  no timestamps) plus a readable twin, so re-alignment is a `git diff`.
- Writes are performed by the agent through the transport (MCP) **only** from an approved plan, with idempotency keys
  per change; the engine records what was applied.

## 6. Commands (engine) and broker tools

- `ai-orch tasks tickets link|unlink ID REF --relation R`, `tickets list [--tracker T]`, `tickets adopt --preview`
- `ai-orch tracker snapshot`, `tracker plan --mode M [--scope ID]`, `tracker apply PLAN --expect-hash H`
  (apply executes through a transport adapter; the Redmine adapter is the MCP server or REST), `tracker status`
- Broker (initiative 16): `tasks.show` and `tasks.list` carry `tickets`; `tracker.plan` (read-only) as an MCP tool;
  `tracker.apply` stays owner-facing (UI/CLI), consistent with the broker's rule for owner-facing actions.

## 7. Open questions for the owner

- Q-a: should `link` mode change issue **status** automatically when the task is `done` (with evidence), or only add
  a note and propose the status change?
- Q-b: where should the plans and snapshots live: in the project (`tasks/_tracker/`, versioned, as the skill
  recommends) or in `.ai-orchestration/` (not versioned)?
