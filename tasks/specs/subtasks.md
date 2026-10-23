# Spec: First-class task hierarchy (N levels, parent → children)

- **Status:** ready (2026-10-17). Revised the same day: N levels instead of two, on owner request.
- **Drives:** initiative [11](../done/11-subtasks/plan.md)
- **Restores and generalizes:** the original `macroplan-authoring` model (agentic-coding-kit, 2026-08-05): initiative → tasks `NN.T` ("one task = one commit") → sub-steps inline. That model is also in [`task-and-state-model`](task-and-state-model.md) §1, where `NN.T` carry "the exact same metadata fields and state transitions as `T###`", and in the "Initiative → NN.T subtasks" tree of [`orchestration-extension-spec`](orchestration-extension-spec.md). The engine never implemented it: `NN.T` inherit the initiative state and carry no metadata, and agent runs (spec 07 §1) are restricted to `T###` because of this.

## 0. Amendments after the Codex review (2026-10-17; normative, each overrides the section it names)

- **S1 — ids are immutable; `tasks move` is removed (§3).** A dotted id is assigned at creation and never changes: run records, inbox `produced`, question `blocks`, branches and commit messages all reference it. Re-parenting is done by creating the node under the new parent and dropping the old one with a reason that names the replacement.
- **S2 — reopening is explicit (§6).** Closed states stay terminal in the state machine. `tasks reopen ID --reason TEXT` (leaves only) sets `open` and moves the node back to its open location. When the node sits in a shipped initiative or in a closed folder, the ancestors are restored too: the initiative returns from `done/` to `tasks/`, its `summary.md` is kept and marked `reopened <date>`, and the links are rewritten.
- **S3 — questions do not move (overrides the §6 table row).** Question files stay in `tasks/questions/` whatever their status, as spec 08 defines; the UI separates open and closed questions by status. This keeps id allocation and restoration unchanged.
- **S4 — `blocks` accepts leaves only (§3).** A question about a container blocks the leaves the asker names, never the container.
- **S5 — derived container state is a total function (§1 Rule 1).** Children are evaluated in this order and the first rule that matches wins:
  1. no children → `open`, with a validator warning "empty container";
  2. every child is `dropped` → `dropped`;
  3. every child is `done`, `done with a caveat` or `dropped` → `done`, or `done with a caveat` when at least one child is;
  4. any child is `in progress`, `delivered`, `bounced` or `verified`, **or** some children are closed (`done`, `done with a caveat`) while others are not → `in progress` (amended 2026-10-17 at the 11.1 review: work on the container has started; the engine already behaved so);
  5. any child is `blocked` → `blocked`;
  6. any child is `waiting` → `waiting`;
  7. otherwise → `open`.

  Nested containers use their own derived state as their child state.
- **S6 — canonical serialization of an expanded node (§1 Rule 3, §2).**
  - The parent keeps a one-line block: `### 07.4 - <title>` followed by the single bullet `- **Expanded:** [07.4-<slug>/](07.4-<slug>/README.md)`.
  - The folder `README.md` starts with `# 07.4 - <title>`, then the same bullet format as a block (no `- key: value` T### header), then optional sections (`## Context`, `## Notes`), then `## Subtasks` with the child blocks, then `## Closed`.
  - Inherited fields are omitted unless set on this node.
  - `expand` and `collapse` round-trip these exact forms byte-for-byte, apart from the moved text.
- **S7 — bullet grammar (§2).**
  - A field bullet is `-` followed by one or more segments separated by ` · ` (space, U+00B7, space).
  - A segment is `**Key:** value`. A value runs until the next `· **` or the end of the line; a literal ` · ` inside a value is written `\·`.
  - Inline code in values (`` `done` ``) is normalised for reading and preserved on write.
  - **`Depends on`** value = an id list (ids matched with exact boundaries: `\b(\d{2}(\.\d+)+|T\d{3,}(\.\d+)*)\b`, separated by `,`), optionally followed by free text in parentheses or after ` — `. `set-deps` rewrites the id list only, and keeps the free text and every other segment byte-for-byte.
  - Test fixtures are copied verbatim from the real plans 06–11.
- **S8 — one id namespace (§1).** Roots are `NN` (initiatives) and `T###` (emergent tasks and microtasks). Children are `<parent>.<n>`. **Microtasks are roots only**, in `tasks/micro/`: they cannot be children, but any node may depend on them. Allocation of `<parent>.<n>` takes the maximum over open children, `## Closed` blocks and `done/` folders of that parent, under the lock.
- **S9 — the logical tree includes archived nodes (§3, §6).** Discovery, roll-up, container expansion for dependencies, and id allocation all read the open locations and the closed ones (`## Closed`, `done/`). A dependency on an empty container is never satisfied, and the validator warns about it.
- **S10 — multi-file operations use an operation hash (§3).** `child add` (when it converts a leaf), `expand`, `collapse`, `reopen`, `ship` and `archive` return an operation plan: every path with its before-hash. Apply requires `--expect-plan-hash` and recomputes the plan under the lock. `--expect-task-hash` stays for single-node mutations.
- **S11 — inheritance per field (§2, overrides the inheritance bullet).**

  | Field | Rule |
  | --- | --- |
  | `Executor`, `Priority`, `Profile`, `Repo`, `Paths` | inherited from the nearest ancestor that sets it; a node's own value overrides it |
  | `Labels` | union of own labels and every ancestor's labels. `set-labels --remove` on an inherited label is refused, with the ancestor that sets it. |
  | `Depends on` | additive: ancestors' dependencies also apply to every descendant |
  | `Size`, `Kind`, `Decider`, `Status`, `Verifier`, `Verification mode` | not inherited |

  Every value is reported with `source: own|inherited:<ancestor id>`.
- **S12 — adding children to a running container is allowed (§3).**
  - The new child starts `open`; the container's derived state and its progress are recomputed.
  - Adding a child under a **leaf** that is past `open` is refused, because a leaf in flight cannot become a container.
  - Active runs on other leaves are not affected.
- **S13 — lane order (plans 10/11):**
  - engine: `11.1 → 11.4 → 10.1 → 10.4`;
  - runs: `07.10 → 11.2 → 07.11 → 07.5`;
  - frontend: `… → 11.3 → 10.2 → 10.5 → …`;
  - 11.2 covers run ids with dotted task ids, block hashes, preview, continuation, history and verdict paths, with tests on `07.4`, `07.4.2` and `T014.1`.

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
