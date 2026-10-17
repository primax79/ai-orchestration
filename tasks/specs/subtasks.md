# Spec: First-class task hierarchy (N levels, parent → children)

- **Status:** ready (2026-10-17). Revised the same day: N levels instead of two, on owner request.
- **Drives:** initiative [11](../11-subtasks/plan.md)
- **Restores and generalizes:** the original `macroplan-authoring` model (agentic-coding-kit, 2026-08-05): initiative → tasks `NN.T` ("one task = one commit") → sub-steps inline. That model is also in [`task-and-state-model`](task-and-state-model.md) §1, where `NN.T` carry "the exact same metadata fields and state transitions as `T###`", and in the "Initiative → NN.T subtasks" tree of [`orchestration-extension-spec`](orchestration-extension-spec.md). The engine never implemented it: `NN.T` inherit the initiative state and carry no metadata, and agent runs (spec 07 §1) are restricted to `T###` because of this.

## 1. Model: a tree of any depth, three rules

Every task is a node. A node may have children.

- **Roots** are initiatives (`NN`) and emergent tasks (`T###`).
- **Children** use dotted ids: `07.4`, `07.4.2`, `T014.1`, `T014.1.3`.
- Initiatives are always containers.

**Rule 1 — only leaves are executed.**

- A leaf is the unit of work: one task = one commit. Runs, `delivered`, `verified` and bounces apply to leaves only.
- A node with children is a **container**. Its state is **derived** and cannot be transitioned by hand:
  - `done` when every child is `done`, `done with a caveat` or `dropped`, and at least one child is not dropped;
  - `dropped` when every child is dropped;
  - `blocked` or `waiting` when any child is, and none is `in progress`;
  - `in progress` when any child is past `open`;
  - otherwise `open`.

**Rule 2 — a dependency on a container means "all of its leaves are closed".**

- Any node can be a dependency.
- A leaf is ready when every dependency (expanded to leaves) is closed, **and** every dependency of its ancestors is closed too: dependencies are inherited downwards.

**Rule 3 — one level of blocks per file; deeper means a folder.**

- Inside a file, children are `### <id> - <title>` blocks. Initiatives keep them in `plan.md`; folder tasks keep them in `README.md` under `## Subtasks`.
- A child that needs children of its own is **expanded** into a folder named `<id>-<slug>/`, with a `README.md` holding its own fields and its children as blocks. The block in the parent file is reduced to a link line.
- Markdown never nests task headings below `###`.

**Depth:** unlimited. `tasks validate` warns beyond depth 4, which suggests turning the subtree into an initiative.

**Microtasks** (spec 10 §5) are always leaves. They may sit at any level as children, in the reduced format.

## 2. Node format (the same at every level)

A block is a heading followed by bullets, as already used in `plan.md`:

```markdown
### 07.4 - Run engine C: worktrees, verify, verdicts

- **Status:** `in progress` · **Executor:** kilo · **Priority:** P1 · **Size:** L · **Kind:** feature · **Labels:** runs
- **Depends on:** 07.3
- **Profile:** `deep-reasoning`
- **Focus files:** ...
- **Goal:** ...
- **Verification:** ...
```

- **Recognised keys:** `Status` (with an optional date in parentheses), `Executor`, `Priority`, `Size`, `Kind`, `Labels`, `Depends on`, `Profile`, `Verification mode`, `Verifier`, `Decider`, `Focus files`/`Paths`, `Goal`, `Steps`, `Verification`, `Handoff`, `Repo`.
- Several keys may share a bullet, separated by `·`. Unknown keys are kept verbatim.
- **Required:** `Goal`, and `Status` for leaves only (container status is derived and never written).
- **Inheritance:** `Executor`, `Priority`, `Profile`, `Labels`, `Repo` and `Paths` are inherited from the nearest ancestor that sets them. The engine reports which values are inherited.
- **Folder form:** a folder node's `README.md` uses the same keys as a `T###` header (`- key: value`). For emergent roots this is the existing header.

## 3. Engine

**Parsing:** one recursive, fence-aware parser (built on the scanner from 08.1). Every node gets: `id`, `parent`, `depth`, `is_leaf`, its fields with their inherited/own source, `derived_state` for containers, and `leaves_done/leaves_total`.

**Transitions (leaves only):**

- They work on blocks and on folder nodes, with the same state machine, lock and `--expect-task-hash`. The hash covers the block text or the folder bundle.
- A block is rewritten in place; every other byte of the file is preserved.
- A transition on a container is refused, with "derived state; transition its leaves".

**Dependencies:**

- `depends-on` accepts any node id.
- Readiness and columns (spec 10) expand containers to their leaves and add the inherited ancestor dependencies.
- Cycles are refused across the expanded graph, including a node that depends on one of its own ancestors or descendants.

**Structure commands** (all under the lock, with `--dry-run` and the hash):

| Command | Effect |
| --- | --- |
| `tasks child add PARENT --title T [--kind …]` | Allocates the next id under the parent. A leaf parent turns into a container: its `Status` bullet is removed and its `Goal` kept. The command is refused if the parent is past `open`, because a leaf already in flight cannot become a container. |
| `tasks expand ID` | Block → folder. |
| `tasks collapse ID` | Folder → block; only for nodes whose children are all leaves stored as blocks. |
| `tasks move ID --to NEW_PARENT` | Re-parents a node: renumbers its ids, rewrites every `depends-on` that points into the moved subtree, and refuses when this would create a cycle. |

**Index:** the Initiatives status cells and their progress (`done: 06.1–06.7; running: 06.8`) are generated from the tree, not hand-edited.

**Everything that took `T###` now takes any node id:**

- `tasks graph`, and spec 10's priority, size, dependency, kind and label commands: on containers they are set and inherited, but they do not change the derived state;
- blocking questions (`blocks` accepts any id; this overrides spec 08 Q1);
- runs (spec 07): leaves only, and the prompt includes the context of the whole ancestor chain;
- the inbox: `tasks new --from-note --parent ID`.

## 4. UI

- **Backlog "Tree" view:**
  - collapsible at any depth;
  - containers show a progress bar (`leaves_done/leaves_total`) and their derived state;
  - "Add child" on any node; "Expand to folder" and "Move" in the node menu.
- **Detail modal:** the same for every node. It shows inherited fields as inherited, with "set here". Containers offer no transition buttons.
- **Kanban:** leaves only, each with a breadcrumb of its ancestors.
- **Timeline (spec 10):** leaves are the cards. Containers are optional swimlanes ("group by ancestor at depth N"). Arrows to a container are drawn to its swimlane.

## 5. Migration

- Existing `plan.md` files are already depth-1 blocks under initiatives. Their `Status` bullets become authoritative.
- The first `sync-index` regenerates the Initiatives status cells; the preview shows the diff before apply.
- Existing folder tasks with `## Steps` stay as they are. Steps are not nodes; they become nodes only when the owner converts them with `tasks child add`.

## 6. Closed work lives apart from open work (owner rule, 2026-10-17)

At every level, closed items (`done`, `done with a caveat`, `dropped`) are physically separated from open ones, so the active tree only shows pending work.

| Item | When it closes | Where it goes |
| --- | --- | --- |
| Emergent root `T###` | on the transition | `tasks/done/<category>/` (existing behaviour) |
| Initiative `NN` | when its derived state becomes closed | `tasks ship NN`: writes `summary.md` (a generated skeleton the closer completes: outcome, deviations, follow-ups) and moves the folder to `tasks/done/NN-<slug>/` |
| Child block (`### id - …`) | on the transition, or on derivation for containers | Moved to a `## Closed` section at the end of the same file. Open blocks stay at the top, and the id and its anchor stay stable. |
| Folder child (`<id>-<slug>/`) | same | `<parent folder>/done/<id>-<slug>/` |
| Question `Q###` | answered or withdrawn | `tasks/questions/closed/` |
| Inbox note | processed or discarded | `tasks/_inbox/analyzed/` (existing behaviour) |

**Rules:**

- **Moves are atomic, under the task-write lock.** Every link that points into a moved path is rewritten in the same operation (`depends-on` stays id-based and needs nothing): Markdown links in `tasks/**`, `sources` headers, `produced` lists, and the index. The result reports the rewritten files. This generalizes the 09.1 follow-up mechanism.
- **Reopening** (`bounced`, or `reopen` for questions and notes) moves the item back to the open location.
- `sync-index` lists closed initiatives in the Initiatives table under a "Closed" sub-table, linking to `done/…`.
- **Validation:**
  - a closed item in an open location → warning, with the exact `tasks archive` command;
  - an open item under `done/` → error.
- `tasks archive [--dry-run]` applies the rule to an existing tree in one go: diff preview, then apply with the hash.
- On 2026-10-17 initiatives 01, 02, 03 and 05 were shipped by hand: retroactive `summary.md`, `git mv` into `done/`, links fixed.
