# UI multi-project: project view and common workspace view (16.9)

- status: draft 1 (2026-10-20); details the interface part of `orchestration-broker-mcp.md` §7b.
- owner requests: "the interface follows the placement rule, with a view per single project or common to the workspace"
  (2026-10-18); "is ai-orchestration-ui / vscode-ai-orchestration ready to read the tasks of the projects inside a
  workspace? Write the detailed spec and start the implementation" (2026-10-20, via the d4science-python-library
  session). Real case: `~/works/d4science-python-library` (no root `tasks/`; four projects
  `d4science-python-library`, `d4science-python-iam`, `d4science-python-resource-registry`,
  `d4science-python-legacy-is`, each with its own `tasks/`; a VS Code multi-root `.code-workspace`).
- today: the backend reads only `<bound folder>/tasks` (51 call sites of `state.workspace / "tasks"` in
  `ai-orchestration-ui/backend/server.py`); one server per project; the VS Code extension binds one folder at a time.
- engine pieces already delivered: workspace/project registry and `projects discover` (16.3), qualified refs,
  `coordinates:`, placement warnings, `tasks move` (16.4). This spec does not depend on the broker (16.5): the UI keeps
  calling the engine CLI directly; it moves to the broker tools later without changing the UI contract.

## 1. Binding: a workspace, not a tasks folder

- The server binds a **workspace root** (`AI_ORCH_WORKSPACE`, the folder picker, or the VS Code bound folder).
- **Projects of the bound workspace**, resolved in this order:
  1. registered workspace (`ai-orch workspace show <root> --json`): its `[[workspace.projects]]` plus `_workspace` if
     `<root>/tasks/00-INDEX.md` exists; inner registered workspaces listed as `sub_workspace` (read-only);
  2. not registered: **read-only discovery** with the engine's rules (`ai-orch projects discover <root> --json` if it
     accepts an unregistered path; otherwise the same rules in the backend: folders with `tasks/00-INDEX.md`, skipping
     hidden folders, git-ignored paths asked of the owning repo, `node_modules`, build/dist/target/venv/scratch/
     fixtures, `.kilo/worktrees`, `references`), shown with a banner "projects discovered, not registered — Register…"
     (the register action uses the engine's preview → apply with hash);
  3. a plain project folder (`<root>/tasks/00-INDEX.md` and no inner projects): a single project, exactly today's
     behaviour (backward compatible).
- Project identity in the UI: `{id: slug, path: relative to the root, kind: project | _workspace | sub_workspace}`.

## 2. Backend

- One resolver replaces every `state.workspace / "tasks"`: `project_root(project_id) -> Path` and
  `tasks_dir(project_id)`. Every engine call for a project runs with that project's root (`--workspace <project root>`
  / `--tasks-dir <project root>/tasks`), so runs, questions, inbox notes, attachments and events stay per project, as
  the engine expects. Unknown project id → 404; a path outside the bound root → 400.
- **API shape:** every existing task/question/inbox/run/attachment/graph endpoint accepts `project` (query parameter
  or path prefix `/api/p/<project>/...`, pick one and use it everywhere). Without `project`: the single project when
  there is one; otherwise 400 `project-required` — except the aggregate endpoints below.
- New endpoints:
  - `GET /api/workspace` → root, registered or discovered, projects (id, path, kind, counts per state, open
    questions, inbox notes), sub-workspaces;
  - `GET /api/workspace/tasks` → the union of all projects' tasks, each with `project`, `qualified_id`
    (`project/ID`), short title, state, priority, kind, and the `coordinates` of `_workspace` tasks resolved to the
    target tasks' live states; paged; filters `project[]`, `state[]`, `kind`, `label`, `text`;
  - `GET /api/workspace/questions`, `/api/workspace/inbox`, `/api/workspace/runs` → unions with a `project` column.
- **Writes** always target one project (the item's own). The aggregate endpoints are read-only.
- **Watching:** file watchers and the event stream per project tree; a change in a project emits
  `{type: changed, project, areas}` on the WebSocket.
- **Performance:** project trees are loaded in parallel and cached per tree hash; the aggregate view must render the
  real `d4science-python-library` workspace (four projects) in under 2 s on a warm cache.

## 3. Web UI

- **Workspace switcher** (top bar): workspace name, then a project selector: "All projects" (common view) or one
  project. The choice is kept per browser tab and in the URL (`?project=iam`); deep links `?project=iam&task=T012`.
- **Project view** = today's views (Backlog, Kanban, Tree, Timeline, Decisions, Inbox, Runs) for one project, bare
  ids.
- **Common view** (All projects):
  - Backlog/Kanban/Tree: items show `project/ID (short title)`, a project chip and colour, filters and grouping by
    project; `_workspace` coordination tasks show their `coordinates` expanded (target id, short title, live state),
    and a warning chip when the engine reports a placement warning;
  - Timeline: one lane per project; cross-project edges only from `coordinates`;
  - Decisions, Inbox, Runs: one list with a project column;
  - creating an item asks for its project (default: the filtered one); opening an item switches the context to its
    project for every write.
- **Dashboard strip**: per-project counts (open, in progress, waiting, delivered, verified), open questions, unread
  inbox, and the "conditional" KPI of T030 when present.
- Unregistered workspace: banner with "Register…" (preview → apply) and "Discover projects" (preview → apply).

## 4. VS Code extension

- Binds the **workspace root**; in a multi-root VS Code workspace it binds the common parent when the folders share
  one (as `d4science-python.code-workspace` does), otherwise the user picks which folder is the root.
- Tree views (Next Up, Initiatives, Use Cases, Decisions) get a top-level node per project in the common view, or a
  project picker in the view title; labels `project/ID (short title)` in the common view, bare ids in a project view.
- The dashboard webview uses the same API through the bridge: every handler takes `project`, and the new aggregate
  messages mirror §2. Parity test updated.

## 5. Out of scope here

Cross-project `depends-on` (v2), cross-workspace views (the "all workspaces" overview of the broker spec), mail.

## 6. Tasks

- 16.9a backend: resolver, `project` parameter on every endpoint, aggregate endpoints, discovery fallback, per-project
  watchers; tests including the four-project layout.
- 16.9b web UI: switcher, project and common views, chips/filters/grouping, coordinates expansion, dashboard strip.
- 16.9c VS Code: root binding in multi-root workspaces, tree views per project, bridge parity.
