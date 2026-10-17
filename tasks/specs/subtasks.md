# Spec: First-class subtasks (parent → child), for initiatives and for emergent tasks

- **Status:** ready (2026-10-17)
- **Drives:** initiative [11](../11-subtasks/plan.md)
- **Restores:** the model of [`task-and-state-model`](task-and-state-model.md) §1. Initiative tasks (`NN.T`) were meant to carry "the exact same metadata fields and state transitions as `T###`", and [`orchestration-extension-spec`](orchestration-extension-spec.md) planned an "Initiative → NN.T subtasks" tree and a "Task & Subtask" detail view. The engine never implemented either: `NN.T` inherit the initiative state and carry no metadata. Agent runs (spec 07 §1) are restricted to `T###` because of this.

## 1. Model: two levels, one task format

| Parent | Children (subtasks) | Where the children live |
| --- | --- | --- |
| Initiative `NN` (a container; it cannot be executed or transitioned) | `NN.T` | `### NN.T - <title>` blocks in `NN-<slug>/plan.md`, or expanded files `NN-<slug>/NN.T-<name>.md` (existing convention) |
| Emergent task `T###` (a folder task) | `T###.N` | `### T###.N - <title>` blocks in the task's `README.md`, under a `## Subtasks` section |

- **Depth is two levels.** Children have no children of their own. Work that needs more depth becomes an initiative.
- **Microtasks** (spec 10 §5) are leaves. They are never parents. A microtask may be referenced from a parent's `## Subtasks` section only by id, as a dependency, not as a child.

## 2. Child format (the same for `NN.T` and `T###.N`)

A heading followed by bullets, as already used in `plan.md`:

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
- Several keys may share one bullet, separated by `·` (the existing style). Unknown keys are kept verbatim.
- **Required:** `Status` and `Goal`. Every other field falls back to the parent's value (`Executor`, `Priority`, `Profile`, `Labels` are inherited) or to the default.
- **Expanded form:** an `NN.T-<name>.md` file uses the same keys as a normal `T###` header (`- key: value`). When both forms exist, the expanded file wins and the block is reduced to a link.

## 3. Engine

**Parsing:** one shared parser for child blocks. It is fence-aware (the scanner from 08.1). Every child becomes a node with the same fields as a `T###`, and the result says which values are inherited.

**Transitions:** `tasks transition 07.4 delivered` works on child blocks and on expanded files.

- The same state machine applies.
- The same lock and `--expect-task-hash` apply; the hash covers the block text for a block, or the file.
- The same blocking-question linkage applies (spec 08: `blocks` now accepts `NN.T` and `T###.N`; this overrides 08 Q1).
- A block is rewritten in place: only its bullets change, and every other byte of the plan or README is preserved.

**Roll-up:**

- **Initiative status** (the Initiatives table in `00-INDEX.md`, a generated cell) is derived:
  - `done` when every child is done, dropped or `done with a caveat`;
  - `in progress` when any child is past `open`;
  - otherwise `open`.
  - The summary `done: 06.1–06.7; running: 06.8` is generated, not hand-edited.
- **A `T###` parent with subtasks:**
  - its state may not move to `delivered` or `done` while a child is open: the transition is refused and the open children are listed;
  - `tasks list` shows `children_done/children_total`.

**Ids:** `NN.T` and `T###.N` are unique by construction. `tasks subtask add T014 --title …` allocates the next `N` under the lock.

**Everything that took `T###` now takes child ids too:** `tasks graph`, the priority/size/dependency/kind/labels commands of spec 10, runs (spec 07: lifts the `T###`-only restriction; a run on a child uses the child's fields with the parent's inheritance), and the inbox `tasks new --from-note --parent ID`.

## 4. UI

- **Backlog "Tree" view:**
  - initiatives and folder tasks, each with its children;
  - progress bars from the roll-up;
  - expand and collapse;
  - children have the same cards as tasks.
- **Detail for a child:** the same modal as for a task. It shows the inherited fields, marked as inherited, and offers "set here".
- **Kanban and Timeline (spec 10):** children appear as cards in their own right, with a parent badge. "Group by parent" is available.
- **"Add subtask"** on any initiative or folder task.

## 5. Migration

- Existing `plan.md` files already use the block form. Their `Status` bullets become authoritative: today the initiative status in the index is hand-written.
- The first `sync-index` after the change regenerates the Initiatives status cells. The preview shows the diff, as for every apply.
