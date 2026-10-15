# Coherence Review — uncommitted `ai-orchestration` work (2026-10-15)

- **Author:** Claude (Architect session `ai-coding-tools-49`)
- **Audience:** the Kilo session orchestrating `ai-orchestration`
- **Scope:** the current *uncommitted* working tree (nothing committed since `186ea65`): `docs/01`–`06`, `bin/ai-orch`, the two Python engines, the consolidated `macroplan-authoring`, and the updated skills.
- **Verdict:** executable layer is sound; **document-level coherence has 5 defects that should be fixed before any commit.**

---

## What is verified OK (do not re-check blindly, but these held)

- `orchestration_config.py` tests: **5 passed**.
- `tasks_engine.py` tests: **5 passed**.
- `ai-orch tasks validate` → validates 9 emergent tasks + 5 initiatives, no errors.
- `ai-orch tasks sync-index --check` → `00-INDEX.md` in sync with task headers.

The executable work is in good shape. The findings below are about **coherence between the design docs, the registry, the workspace pseudo-task, and the renamed repo** — exactly the class of problem a green test run and a "looks good" report do not catch.

---

## Findings (ranked by severity)

### F1 — `CONTEXT.md` points at a repo that no longer exists (BROKEN NOW)

The repo was renamed `ai-architect-executor → ai-orchestration`, but `tasks/CONTEXT.md` still describes `../ai-architect-executor/` as a separate sibling:

- Codebase Map (lines ~11–15): lists `../ai-architect-executor/plugins/...` as the home of the skills that are **actually in this repo**.
- Command / Verification Surface (lines ~27–32): every command invokes `../ai-architect-executor/scripts/...` and `../ai-architect-executor/plugins/...`.

**Verified:** `../ai-architect-executor` does not exist on disk. Any agent that follows those verification commands fails immediately.

**Fix:** rewrite the Codebase Map + Command/Verification Surface to local paths (this repo is `ai-orchestration/`, the scripts are under `./scripts/` and `./plugins/...`). This is the most concrete breakage.

### F2 — Two conflicting initiative taxonomies; the one in `docs/03` does not exist on disk

- `docs/03 §3` describes the roadmap as initiatives `01-task-model-spec`, `02-python-core-and-cli`, `03-web-server-and-dashboard`, `04-vscode-extension`.
- **Verified:** none of those four directories exist under `tasks/`.
- The real tree is `01-repo-consolidation`, `02-task-and-config-spec`, `03-skill-and-script-engine`, `04-methodology-refinements`, `05-cli-and-ui-handoff` — which is what `00-INDEX.md` governs.

**Fix:** pick ONE taxonomy as truth. If `00-INDEX.md` (5 initiatives) is truth, update `docs/03 §3` to match. If the `docs/03` 4-initiative plan is the intended new direction, then the `tasks/` tree + INDEX must be restructured to it. They cannot both ship.

### F3 — Workspace pseudo-task `T013` mirrors the wrong plan

`../tasks/tooling/T013-ai-orchestration-project.md` is supposed to mirror `ai-orchestration/tasks/00-INDEX.md` (its own Verification says "in sync"). Instead it lists the 4 `docs/03` initiatives (all `open`), not the 5 real INDEX initiatives. This violates "the INDEX is the state" and would hand any agent the wrong map.

**Fix:** regenerate `T013`'s "Project task tree state" block from the real `00-INDEX.md` once F2 is resolved.

### F4 — The registry lags the work actually done

`00-INDEX.md` still lists `01.1`/`01.2` as Next up and `03.1` as "ready", but on disk `docs/00`–`06`, `bin/ai-orch`, and both Python engines are **already done**. The INDEX is "in sync" with headers only because no header was advanced. State does not reflect reality.

**Fix:** advance the headers/states of the tasks that are actually delivered, then re-run `ai-orch tasks sync-index`.

### F5 — The naming plan (`docs/06`) conflicts with the consolidation just performed

`docs/06` proposes renaming `macroplan-authoring → task-pipeline`, `interactive-role-setup → orchestration-setup`, `delegation-roi-analysis → orchestration-metrics`, `task-delegation → task-worktree-ops`, `headless-executor-contract → executor-contract`. But the consolidation just imported `macroplan-authoring` under the **old** name.

**Fix (decision needed):** either execute the `docs/06` renames *before* committing (so the consolidation lands with final names and we avoid churn), or explicitly mark `docs/06` as deferred/future and keep current names. Do not commit in the current half-way state.

---

## Suggested order of operations

1. **Decide the taxonomy (F2)** — this unblocks F3 and F4.
2. **Fix `CONTEXT.md` paths (F1)** — independent, do it now, it is broken.
3. **Decide on the naming plan (F5)** — before committing, not after.
4. **Advance task states + re-sync INDEX (F4)**, then **regenerate `T013` (F3)**.
5. Only then commit, in coherent slices.

## Note on delegation quality (workspace telemetry, 30d)

44 defects logged, issue rate 0.50/run; dominant category is `report-inaccurate` (7 major + 5 minor) and 2 `security-bypass [critical]`. Reports tend to overstate completion — hence this review targets document coherence, which a self-report will not surface. Verify live, not only by test pass.
