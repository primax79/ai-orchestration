# Spec: Timeline (Gantt) view with dependencies

- **Status:** ready (2026-10-17)
- **Drives:** initiative [10](../10-timeline-gantt/plan.md)
- **Origin:** owner request (2026-10-17): a Gantt chart with dependencies, in the UI. A hand-written Mermaid snapshot exists in [`../gantt.md`](../gantt.md). This spec replaces it with one generated from the task data.

## 1. Goal

The UI shows every task of the workspace as a bar on a time axis, with **arrows for dependencies**. Each bar is coloured by state and grouped by initiative or category.

- Done tasks sit on their real dates.
- Open tasks are scheduled after their dependencies, using an estimate.
- The critical path is highlighted.
- Clicking a bar opens the task.

## 2. Data (engine): `ai-orch tasks graph --json`

A read-only command in `tasks_engine.py` that returns `{nodes, edges, lanes, critical_path, generated_at}`.

**Nodes:**

- **Emergent tasks (`T###`):** taken from their headers (`state`, `depends-on`, `executor`, `priority`).
- **Initiative tasks (`NN.T`):** parsed from each `NN-<slug>/plan.md` `### NN.T - <title>` block. From that block's bullets:
  - `**Status:**` gives the state and, optionally, a date in parentheses: `done (2026-10-16)`;
  - `**Depends on:**` gives the dependencies: a list of `NN.T`/`T###` ids, and plain text after the ids is ignored;
  - `**Estimate:**` is optional: `30m`, `2h`, `1d`, where `1d` = 8 working hours;
  - `**Lane:**` is optional: a free label.
- **Initiatives:** `NN` nodes as group headers, with derived start and end dates.

**Edges:**

- `{from, to, kind: "depends"|"lane"}`.
- Lane edges are derived when two consecutive tasks share a `**Lane:**` value and appear in that order in the plan files.

**Dates:**

- **Done tasks:** `start = end - estimate`, where `end` is the date given in `Status`. If that date is missing, use the git date of the commit that set the task to done, else the file's mtime.
- **Active tasks** (`in progress`, `delivered`): start = the date of the transition, when known, else now.
- **Open tasks:** earliest start = max(now, end of every dependency); default estimate 1h.
- The schedule ignores calendars and parallelism limits, except that tasks in the same lane are serialized.

**Other outputs:**

- `critical_path`: the longest chain by duration among the tasks that are not done.
- **Validation (`tasks validate`):**
  - a dependency on an unknown id → warning;
  - a dependency cycle → error.

## 3. UI

- **A "Timeline" tab.**
  - An SVG Gantt, built with no new runtime dependency: a React component with plain SVG.
  - Time axis with zoom (hours, days, weeks) and a today marker.
  - Rows grouped by initiative; emergent tasks are grouped by category.
  - Bars coloured by state, with the same palette as the Kanban.
  - **Dependency arrows** drawn as elbow connectors from the end of one bar to the start of the next. Lane edges are dashed.
  - The critical path is outlined.
  - Hovering a bar shows a tooltip (id, title, state, estimate, dependencies).
  - Clicking a bar opens the existing task modal for `T###`, or a read-only plan excerpt for `NN.T`.
  - Filters: initiative, state, "hide done".
- **Live updates:** the tab reloads on `changed` events for `tasks`.
- **Safe rendering:** titles are rendered as text (spec 06 A12).
- **VS Code:** the same component in the webview, with no extra handler beyond `getGraph`.

## 4. Out of scope

- Editing dates or dependencies by dragging. The view is read-only; the plans stay the source of truth.
- Resource levelling beyond lanes.
