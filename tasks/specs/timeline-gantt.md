# Spec: Abstract timeline — dependencies and priorities

- **Status:** ready (2026-10-17), revised the same day after owner feedback: no dates and no estimates; dependency management, priority management, and task size (small / medium / long).
- **Drives:** initiative [10](../10-timeline-gantt/plan.md)

## 1. Goal

In the UI, the owner sees and manages **what comes before what**, and **what matters most**. Nothing is shown in hours or dates.

- **Columns are steps.** A task sits in the column right after the latest of its open dependencies. Column 0 holds the tasks that are **ready now**: every dependency is done.
- **Arrows are dependencies.** They can be added and removed from the UI. Every change is validated: unknown ids are refused, and so are cycles.
- **Priority** (`P0`–`P3`) orders the tasks inside each column and sets the **Ready queue**: the ready tasks sorted by priority. Priorities are edited from the UI.
- **Size** (`S` small, `M` medium, `L` long) is a relative weight, not a duration. It sets the card width (S = 1 unit, M = 2, L = 3), so a heavy chain is visible at a glance. Sizes are edited from the UI. A task without a size counts as `M` and is drawn with a dashed border.
- Done tasks are hidden by default. They can be shown greyed out in a "Done" column on the left.

## 2. Data (engine)

### 2.1 Reading: `ai-orch tasks graph --json [--mermaid]`

A read-only command in `tasks_engine.py`.

**Nodes:**

- **Emergent tasks (`T###`):** from their headers (`state`, `priority`, `priority-reason`, `depends-on`, `executor`, `next-up`, and the new optional extension field `size`). `size` is added to the optional extensions of the header closed set (after `verifier`), in `task-and-state-model.md` and in the engine.
- **Initiative tasks (`NN.T`):** parsed from each `NN-<slug>/plan.md` `### NN.T - <title>` block. From that block's bullets:
  - `**Status:**` gives the state;
  - `**Depends on:**` gives the dependencies: `NN.T`/`T###` ids, and plain text around the ids is ignored;
  - `**Size:**` is optional: `S`, `M` or `L`;
  - `**Priority:**` is optional: `P0`–`P3`. Without it, the task takes the initiative's position: the `Priority` column of the Initiatives table, mapped to P1 for the first two initiatives in that table, P2 for the next two, and P3 for the rest. The UI shows this as an inherited value.

**Output:** `{nodes, edges, columns, ready_queue, longest_chain}`.

- Each node: `id`, `kind` (`emergent`/`initiative_task`), `title`, `group` (initiative `NN` or the category), `state`, `priority` (with `priority_source`: `own` or `inherited`), `size` (with `size_source`: `own` or `default`), `depends_on`, `column`, `blocked_by` (the open dependencies).
- `columns`: the step index for every open task (0 = ready).
- `ready_queue`: the column-0 tasks sorted by priority, then `next-up: yes` first, then id.
- `longest_chain`: the heaviest chain of open tasks, by the sum of sizes (S=1, M=2, L=3), highlighted in the UI.
- `totals`: the sum of open sizes per group and overall, e.g. `5 S, 7 M, 2 L`.
- `--mermaid`: a `flowchart LR` with one subgraph per column and nodes coloured by priority. It replaces any hand-written graph.

**Validation (`tasks validate`):** a dependency on an unknown id → warning; a dependency cycle → error.

### 2.2 Writing (all under the task-write lock, atomic, with hash preconditions — spec 06 A9)

| Command | Effect |
| --- | --- |
| `tasks set-priority ID P# [--reason TEXT] [--expect-hash H]` | **`T###`:** rewrites `priority` and, when given, `priority-reason`. **`NN.T`:** writes or updates the `**Priority:**` bullet in the plan. |
| `tasks set-size ID S\|M\|L [--expect-hash H]` | **`T###`:** writes the `size` header field. **`NN.T`:** writes or updates the `**Size:**` bullet. |
| `tasks set-deps ID --add ID... --remove ID... [--expect-hash H]` | **`T###`:** rewrites `depends-on`. **`NN.T`:** rewrites the ids of the `**Depends on:**` bullet and keeps its trailing free text. Refused when it would create a cycle (the error names the cycle) or reference an unknown id. |

The hash covers the task bundle for `T###`, or the plan file for `NN.T`. Every command supports `--dry-run`, which returns the diff and the hash.

## 3. UI — "Timeline" tab

- **Layout.**
  - Columns left to right: the optional Done column, Ready (0), then 1, 2, …
  - Cards grouped by initiative or category through a colour band and the id prefix, sorted by priority inside each column.
  - **Arrows are SVG elbow connectors** from each dependency to its dependent, drawn over the card grid. The `longest_chain` is outlined.
- **Cards** show the id, a short title, a state chip, a priority chip and a size chip. Card width follows the size. Clicking a card opens the task: the existing modal for `T###`, a read-only plan excerpt for `NN.T`.
- **Ready queue panel** (right side): the column-0 tasks by priority. This is "what to start next".
- **Priority management.** The priority chip is a dropdown (P0–P3), with an optional reason field. Changes go through preview → confirm → apply (spec 06 pattern). When the task inherits its priority, a "set own priority" action creates the bullet.
- **Size management.** The size chip is a dropdown (S/M/L), with preview → confirm. The header of each column and group shows its totals.
- **Dependency management.**
  - "Add dependency" on a card opens a picker of the other open tasks; ids that would create a cycle are shown disabled, with the reason.
  - Clicking an arrow offers "Remove dependency".
  - Both go through preview → confirm.
- **Filters:** initiative or category, state, "show done", "only the chain of the selected task" (its ancestors and descendants).
- **Live updates:** the tab reloads on `changed` events for `tasks`.
- **Safe rendering:** titles are rendered as text (spec 06 A12).
- **VS Code:** the same component in the webview. The handlers are `getGraph`, `setPriority` and `setDeps`, each with preview.

## 4. Out of scope

- Dates, estimates and calendars.
- Reordering by drag. Priority and dependencies are the only ordering inputs.

## 5. Microtasks (added 2026-10-17)

A **microtask** is a lightweight emergent task for very small work: a bug, a fix, a chore, a docs touch-up. It is **not a separate type**. It is a `T###` in a lighter form, so dependencies, priority, timeline, runs and blocking questions all apply unchanged.

- **Location:** `tasks/micro/T###-<slug>.md`. `micro` is a normal category, with its own `README.md`.
- **Header** (closed set, in this order): `id`, `title`, `kind` (`bug`, `fix`, `chore`, `docs`), `priority`, `state`, `executor`, `paths`, `depends-on`. The other core fields are not required.
- **Body:** one required section, `## What`. It says what to change, and optionally "done when …". No Goal/Steps/Verification.
- **Size** is always `XS`, the weight below `S` (S=1, M=2, L=3, XS=0.5). In the timeline it is drawn as a small pill.
- **Validator:** `tasks validate` recognises the `micro` category and applies this reduced schema. A microtask that grows past the format (it needs steps or a verification plan) is **promoted**: `tasks promote T###` moves it to a chosen category and adds the missing header fields and sections, keeping the id and the links.
- **Creation:**
  - `tasks micro --title T --kind bug [--priority P2] [--paths …]` allocates the id under the task-write lock;
  - from the inbox (spec 09), a `bug` note can be converted directly into a microtask;
  - in the UI, a one-line quick-add form sits in the Backlog and Timeline tabs.
- **Batch runs** (initiative 07 follow-up):
  - `run start --batch T014,T015,T016` sends several microtasks of the **same target repo** to one executor in one run, with one commit per microtask;
  - each microtask's state is tracked separately;
  - verification is per microtask, but a single verify run can check the whole batch.

## 6. Kind and labels (added 2026-10-17)

Two classification fields, valid on every task (microtasks and full tasks):

- **`kind`**, one value from a fixed set: `feature`, `bug`, `fix`, `chore`, `docs`, `investigation`.
  - Required for microtasks, optional for full tasks.
  - `T###`: header field `kind`, added to the optional extensions of the header closed set.
  - `NN.T`: bullet `**Kind:**`.
  - The UI shows a small icon per kind.
- **`labels`**, free tags, any number of them.
  - Format: `[a-z0-9][a-z0-9-]*`, at most 24 characters, comma-separated.
  - `T###`: header field `labels`, added to the optional extensions.
  - `NN.T`: bullet `**Labels:**`.
  - Examples: `ui`, `security`, `regression`, `kilo-mcp`, `needs-owner`.
- **Engine:**
  - `tasks set-kind ID KIND` and `tasks set-labels ID --add L... --remove L...` follow the same pattern as `set-priority`: task-write lock, `--expect-hash`, `--dry-run`.
  - `tasks list` and `tasks graph` accept `--kind` and `--label` (repeatable; AND across different filters, OR within the same filter) and expose `kind`/`labels` on every node.
  - `tasks labels` lists every label in use, with its count, for autocomplete.
  - The validator checks the label format and the `kind` set.
- **UI:**
  - kind icon and label chips on Backlog cards, Kanban cards and Timeline cards;
  - each label has a deterministic colour from a hash of its name;
  - a filter bar shared by Backlog, Kanban and Timeline (kind, labels, initiative, state, priority, size);
  - a label editor with autocomplete from `tasks labels`, going through preview → confirm;
  - a "group by label" option in the Timeline.
- **Inbox (spec 09):** a note's `kind` (`bug`, `idea`, …) and its `about` are carried into the task or microtask created from it: `bug` → `kind: bug`, and the repo names in `about` → labels.
