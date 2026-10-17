# Spec: Abstract timeline — dependencies and priorities

- **Status:** ready (2026-10-17), revised the same day after owner feedback: no dates and no estimates; dependency management and priority management only.
- **Drives:** initiative [10](../10-timeline-gantt/plan.md)

## 1. Goal

In the UI, the owner sees and manages **what comes before what**, and **what matters most**. Nothing is shown in hours or dates.

- **Columns are steps.** A task sits in the column right after the latest of its open dependencies. Column 0 holds the tasks that are **ready now**: every dependency is done.
- **Arrows are dependencies.** They can be added and removed from the UI. Every change is validated: unknown ids are refused, and so are cycles.
- **Priority** (`P0`–`P3`) orders the tasks inside each column and sets the **Ready queue**: the ready tasks sorted by priority. Priorities are edited from the UI.
- Done tasks are hidden by default. They can be shown greyed out in a "Done" column on the left.

## 2. Data (engine)

### 2.1 Reading: `ai-orch tasks graph --json [--mermaid]`

A read-only command in `tasks_engine.py`.

**Nodes:**

- **Emergent tasks (`T###`):** from their headers (`state`, `priority`, `priority-reason`, `depends-on`, `executor`, `next-up`).
- **Initiative tasks (`NN.T`):** parsed from each `NN-<slug>/plan.md` `### NN.T - <title>` block. From that block's bullets:
  - `**Status:**` gives the state;
  - `**Depends on:**` gives the dependencies: `NN.T`/`T###` ids, and plain text around the ids is ignored;
  - `**Priority:**` is optional: `P0`–`P3`. Without it, the task takes the initiative's position: the `Priority` column of the Initiatives table, mapped to P1 for the first two initiatives in that table, P2 for the next two, and P3 for the rest. The UI shows this as an inherited value.

**Output:** `{nodes, edges, columns, ready_queue, longest_chain}`.

- Each node: `id`, `kind` (`emergent`/`initiative_task`), `title`, `group` (initiative `NN` or the category), `state`, `priority` (with `priority_source`: `own` or `inherited`), `depends_on`, `column`, `blocked_by` (the open dependencies).
- `columns`: the step index for every open task (0 = ready).
- `ready_queue`: the column-0 tasks sorted by priority, then `next-up: yes` first, then id.
- `longest_chain`: the longest chain of open tasks by count, highlighted in the UI.
- `--mermaid`: a `flowchart LR` with one subgraph per column and nodes coloured by priority. It replaces any hand-written graph.

**Validation (`tasks validate`):** a dependency on an unknown id → warning; a dependency cycle → error.

### 2.2 Writing (all under the task-write lock, atomic, with hash preconditions — spec 06 A9)

| Command | Effect |
| --- | --- |
| `tasks set-priority ID P# [--reason TEXT] [--expect-hash H]` | **`T###`:** rewrites `priority` and, when given, `priority-reason`. **`NN.T`:** writes or updates the `**Priority:**` bullet in the plan. |
| `tasks set-deps ID --add ID... --remove ID... [--expect-hash H]` | **`T###`:** rewrites `depends-on`. **`NN.T`:** rewrites the ids of the `**Depends on:**` bullet and keeps its trailing free text. Refused when it would create a cycle (the error names the cycle) or reference an unknown id. |

The hash covers the task bundle for `T###`, or the plan file for `NN.T`. Every command supports `--dry-run`, which returns the diff and the hash.

## 3. UI — "Timeline" tab

- **Layout.**
  - Columns left to right: the optional Done column, Ready (0), then 1, 2, …
  - Cards grouped by initiative or category through a colour band and the id prefix, sorted by priority inside each column.
  - **Arrows are SVG elbow connectors** from each dependency to its dependent, drawn over the card grid. The `longest_chain` is outlined.
- **Cards** show the id, a short title, a state chip and a priority chip. Clicking a card opens the task: the existing modal for `T###`, a read-only plan excerpt for `NN.T`.
- **Ready queue panel** (right side): the column-0 tasks by priority. This is "what to start next".
- **Priority management.** The priority chip is a dropdown (P0–P3), with an optional reason field. Changes go through preview → confirm → apply (spec 06 pattern). When the task inherits its priority, a "set own priority" action creates the bullet.
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
