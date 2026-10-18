# 03 - Configuration & Task Management Skill + Python Scripts

- short: Config and task scripts

> **Derived from specs:** [`../specs/orchestration-config-and-agents-md.md`](../../specs/orchestration-config-and-agents-md.md), [`../specs/task-and-state-model.md`](../../specs/task-and-state-model.md)

## Tasks

### 03.1 - Complete `orchestration_config.py`, Unit Tests, and `interactive-role-setup` Skill Update
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** Config engine completion
- **Focus files:** `plugins/shared/skills/interactive-role-setup/scripts/orchestration_config.py`, `plugins/shared/skills/interactive-role-setup/scripts/test_orchestration_config.py`, `plugins/shared/skills/interactive-role-setup/SKILL.md`
- **Steps:**
  1. Write comprehensive `pytest` unit tests in `plugins/shared/skills/interactive-role-setup/scripts/test_orchestration_config.py` testing:
     - Global + Project `orchestration.toml` deep merge;
     - `set-profile` (global and project scopes);
     - `validate` (catching `xhigh` on unsupported models, invalid verification modes, unknown tools);
     - `render-agents-md` (`--apply` and `--check`, preserving content outside `<!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration -->` markers and rendering the `ricerca_auto`-style tables).
  2. Update `plugins/shared/skills/interactive-role-setup/SKILL.md` to guide the user through the new multi-tool Global + Project `orchestration.toml` setup, cross-agent verification routing, and `render-agents-md` workflow using `scripts/orchestration_config.py`.
- **Verification:**
  - `pytest plugins/shared/skills/interactive-role-setup/scripts/test_orchestration_config.py` passes 100%.
  - `python3 scripts/generate_skill_indices.py` exits 0.
- **Commit:** Single commit scoped to `03.1`.

### 03.2 - Implement `tasks_engine.py` (Deterministic Task Parser, Validator, State Transitions & `00-INDEX.md` Sync)
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15) · **Short:** Tasks engine
- **Focus files:** `plugins/architect-side/skills/macroplan-authoring/scripts/tasks_engine.py`, `plugins/architect-side/skills/macroplan-authoring/scripts/test_tasks_engine.py`
- **Steps:**
  1. Implement `tasks_engine.py` (stdlib-only Python, `--json` support on all subcommands):
     - `list [--tasks-dir <dir>] [--json]`: parses all `T###` and `NN-<slug>` tasks into structured JSON.
     - `validate [--tasks-dir <dir>] [--json]`: checks unique IDs (including `done/`), closed header order, valid states/priorities/profiles, DAG acyclicity on `depends-on`, relative Markdown links, and verification-gate invariants.
     - `transition <task_id> <new_state> [--actor <actor>] [--verifier <verifier>] [--reason <text>] [--tasks-dir <dir>]`: enforces the state machine guards from `tasks/specs/task-and-state-model.md` (e.g. blocks `in progress → done`, enforces `verifier != executor` or owner approval on `delivered → verified`, handles `git mv` to `done/` on closure) and appends a timestamped log entry to `PROGRESS.md`.
     - `sync-index [--tasks-dir <dir>] [--apply] [--check]`: deterministically regenerates or checks `tasks/00-INDEX.md` (`Next up`, `Tasks by category`, `Decisions waiting`, `Done`) from the task headers on disk.
  2. Write `test_tasks_engine.py` covering parsing, validation errors, legal/illegal state transitions, cross-agent verification guard, and `sync-index`.
- **Verification:**
  - `pytest plugins/architect-side/skills/macroplan-authoring/scripts/test_tasks_engine.py` passes 100%.
  - `python3 plugins/architect-side/skills/macroplan-authoring/scripts/tasks_engine.py validate --tasks-dir tasks` exits 0.
- **Commit:** Single commit scoped to `03.2`.
