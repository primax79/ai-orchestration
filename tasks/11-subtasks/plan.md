# 11 - First-class task hierarchy (N levels)

> **Derived from:** [`../specs/subtasks.md`](../specs/subtasks.md). It comes **before** initiative 10's engine work: 10.1 builds `tasks graph` on the child parser from 11.1. Lane order: see `../06-control-plane-safety/plan.md`.

## Tasks (One Task = One Commit)

### 11.1 - Engine: recursive node parser, inheritance, leaf-only transitions, derived container state, container dependencies, structure commands (`child add`, `expand`, `collapse`, `reopen`; no `move`, spec S1)

- **Status:** `done` (2026-10-17; claude; merged into main) · **Size:** L · **Profile:** `deep-reasoning` · **Depends on:** 09.1 (same file) · **Note:** the biggest engine task so far; review in two passes (parser and state first, structure commands second) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md`, `tasks/specs/blocking-questions.md` (`blocks` accepts child ids)
- **Goal:** Spec §1–§3 and §5:
  - the three rules at any depth;
  - `transition` on a block rewrites only that block, byte-for-byte elsewhere;
  - transitions on containers are refused;
  - the Initiative status cells are generated;
  - questions may block any node.
- **Verification:**
  - Tests:
    - parsing at depth 1–5 (blocks plus nested folders), and the depth-4 warning;
    - `·` multi-key bullets and inheritance;
    - a block transition leaves the rest of the file byte-identical;
    - every derived-state rule;
    - dependency on a container expands to its leaves;
    - inherited ancestor dependencies;
    - cycles through ancestors are refused;
    - `child add` turns a leaf into a container and is refused when the leaf is in flight;
    - `expand`/`collapse` round-trip;
    - every S5 derived-state rule, the S7 bullet grammar on fixtures copied from the real plans, S8 allocation across archived children, S10 operation hashes, and S11 inheritance per field;
    - a question blocking `07.4`.
  - Live: `tasks list --json` on this repo shows every 06–11 child with its real state.
  - Live: `sync-index --check` shows the generated initiative status cells; the preview diff is reviewed before apply.

### 11.2 - Runs on child tasks

- **Status:** `done` (2026-10-17) · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1, 07.4 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`, `tasks/specs/agent-runs-from-ui.md` (§1 scope note)
- **Goal:** Spec §3: lift the `T###`-only restriction of spec 07 §1. Run prompts include the parent context (initiative `plan.md` header or folder `README`/`CONTEXT`) plus the child block.
- **Verification:** Tests with the stub agent: an execute run on `NN.T` moves the block to `in progress`; mark-delivered and verify on the block. All unit tests pass.

### 11.3 - UI: collapsible tree at any depth, node detail with inheritance, add child, expand, move, breadcrumbs

- **Status:** `delivered` (2026-10-18; claude; merged; 51 backend tests; Kilo Playwright on a scratch copy (tree, progress bars, add subtask T050.1); prior TaskDetailModal features preserved (Structured/Raw, attachments, runs, questions); owner live check pending) · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 11.1, 06.8 (frontend lane) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `frontend/src/**`
- **Goal:** Spec §4.
- **Verification:** Live with Playwright on a scratch copy of this repo's `tasks/`: the tree shows 06–11 with progress bars; transitioning a child updates its block and the roll-up; "Add subtask" on a folder task creates `T###.1`.

### 11.4 - Engine: closed-apart placement at every level (`tasks ship`, `## Closed` section for blocks, link rewriting, `tasks archive`; questions stay in place per S3)

- **Status:** `delivered` (2026-10-18; claude; merged; 229 tests; archive dry-run on the real tree plans 47 closed blocks into Closed sections (not applied: touches plan 15 of another session; owner decision)) · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1 (same file) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `plugins/architect-side/skills/task-pipeline/SKILL.md` ("Ship" step), `tasks/specs/blocking-questions.md` (closed questions location)
- **Goal:** Spec §6.
- **Verification:**
  - Tests:
    - a leaf block closing moves to `## Closed`, and its reopening moves back;
    - a folder child closing moves to `done/` under its parent;
    - an initiative whose last leaf closes is shipped with `tasks ship`, and the links in specs and index are rewritten;
    - questions never move (S3, spec 12 E11);
    - `tasks archive --dry-run` on a fixture with misplaced items shows the plan and writes nothing;
    - every relative Markdown link in `tasks/**` still resolves after each operation (a link checker is part of the test).
  - Live: `tasks archive --dry-run` on this repo reports nothing to do.

### 11.5 - Legacy plan normalization: detection, `normalize` run mode, preview/apply

- **Status:** `done` (2026-10-17) · **Profile:** `deep-reasoning` · **Depends on:** 11.1, 07.4 · **Repo:** `ai-orchestration/` (+ `ai-orchestration-ui/` for the UI part, after 11.3)
- **Origin:** owner, 2026-10-17, on `ricerca_auto`: all 11 initiative plans are free-form (`- **T1 — …**` bullets, `### 3.1 …` sections, `### 01.1 — …` with an em dash), so the engine parses no task blocks and shows each initiative as one synthetic `INIT-NN` card whose detail fails ("Task INIT-11 file not found"). "La nostra skill non dovrebbe normalizzare e sistemare i task?"
- **Goal:**
  - **Detection (engine, deterministic):** `tasks validate` warns, per plan, "no canonical task blocks; found N candidate legacy tasks in plan.md", and `tasks list` parses table tasks and heading tasks with em/en dash separators cleanly.
  - **`tasks upgrade`** upgrades older tasks trees, scaffolds standard directories, and normalizes `tasks/AGENTS.md`.
  - **UI & Webview:** `getTaskDetail` renders plan content for `INIT-NN` and table-based tasks without throwing 404. All unit tests pass.

### 11.6 - 11.1 review follow-ups: S10 enforcement, full `reopen`, children of `T###`, CLI tests

- **Status:** `done` (2026-10-18; claude; merged) · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1 · **Repo:** `ai-orchestration/`
- **Origin:** review of 11.1 (2026-10-17), items the merged engine does not cover yet.
- **Goal:**
  - S10: `--expect-plan-hash` required on apply for `child add`, `expand`, `collapse`, `reopen` (today optional);
  - `reopen` writes `--reason` and restores ancestors (S2) for nodes still in place (the `done/` and `## Closed` cases stay with 11.4);
  - `child add` / `set-labels` on file and folder nodes (`T014.1`), and `tasks new --from-note --parent ID` (spec §3);
  - `set-deps` on an emergent file rewrites only its header line;
  - `tasks/specs/blocking-questions.md`: `blocks` accepts child ids;
  - CLI-level tests for `child add`, `expand`, `collapse`, `reopen`, `set-deps`, `set-labels`, `expand`/`collapse` at depth > 2, and the generated Initiative status cells in `sync-index`.
- **Verification:** the tests above; `validate` clean on this repo and on `ricerca_auto` (read-only).
