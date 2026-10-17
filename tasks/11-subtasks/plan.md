# 11 - First-class subtasks (parent → child)

> **Derived from:** [`../specs/subtasks.md`](../specs/subtasks.md). It comes **before** initiative 10's engine work: 10.1 builds `tasks graph` on the child parser from 11.1. Lane order: see `../06-control-plane-safety/plan.md`.

## Tasks (One Task = One Commit)

### 11.1 - Engine: child-block parser, metadata with inheritance, transitions on blocks, roll-up, `tasks subtask add`

- **Status:** `open` · **Size:** L · **Profile:** `deep-reasoning` · **Depends on:** 09.1 (same file) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md`, `tasks/specs/blocking-questions.md` (`blocks` accepts child ids)
- **Goal:** Spec §1–§3 and §5:
  - `transition` on a block rewrites only that block, byte-for-byte elsewhere;
  - the Initiative status cells in the index are generated;
  - a `T###` parent refuses `delivered`/`done` while a child is open;
  - questions may block children.
- **Verification:**
  - Tests: block parsing with the `·` multi-key bullets and inheritance; transition on a block (the rest of `plan.md` stays byte-identical); expanded-file precedence; roll-up rules; parent gate; `subtask add` id allocation; a question blocking `07.4`.
  - Live: `tasks list --json` on this repo shows every 06–11 child with its real state.
  - Live: `sync-index --check` shows the generated initiative status cells; the preview diff is reviewed before apply.

### 11.2 - Runs on child tasks

- **Status:** `open` · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1, 07.4 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`, `tasks/specs/agent-runs-from-ui.md` (§1 scope note)
- **Goal:** Spec §3: lift the `T###`-only restriction of spec 07 §1. Run prompts include the parent context (initiative `plan.md` header or folder `README`/`CONTEXT`) plus the child block.
- **Verification:** Tests with the stub agent: an execute run on `NN.T` moves the block to `in progress`; mark-delivered and verify on the block.

### 11.3 - UI: Tree view, child detail, "Add subtask", parent badges

- **Status:** `open` · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 11.1, 06.8 (frontend lane) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `frontend/src/**`
- **Goal:** Spec §4.
- **Verification:** Live with Playwright on a scratch copy of this repo's `tasks/`: the tree shows 06–11 with progress bars; transitioning a child updates its block and the roll-up; "Add subtask" on a folder task creates `T###.1`.
