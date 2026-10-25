# T050 upgrade and sync-index preserve project-specific content; per-project extension fields

- id: T050
- title: upgrade and sync-index preserve project-specific content; per-project extension fields
- category: engine
- priority: P1
- priority-reason: upgrade/sync-index destroy project rules and registry columns; porting_liferay cannot adopt the current engine and warns its sessions not to run them
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N049 (porting_liferay, T124 there)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Read tasks/engine/T050-upgrade-and-sync-index-preserve-project-specific-c.md, do the open steps, run the Verification, update the task and the registry.
- verifier: porting_liferay
- verify-by: porting_liferay
- short: Non-destructive upgrade

## Goal

upgrade never replaces an existing tasks/AGENTS.md: it adds or refreshes a managed block between markers and keeps everything else; sync-index rewrites only its generated regions, keeps extra columns a project defined (e.g. Owner) and the project's Next up order unless asked, and never turns companion files into task rows; upgrade exits 0 on success with a clear plan; a per-project config ([tasks] extension_fields in the project's orchestration.toml, or a declaration in tasks/AGENTS.md) lets validate accept project-specific header fields such as 'area'. Verified on a scratch copy of ~/works/gcube/porting_liferay/tasks (read-only on the original): the diff keeps their rules and columns.

## Steps

- [x] Non-destructive `tasks/AGENTS.md` in `upgrade`: wrap managed convention in `<!-- ai-orch:managed begin -->` ... `<!-- ai-orch:managed end -->`, preserving all project-specific content outside markers byte-for-byte; support `--dry-run`/`--preview` and `--apply --expect-hash`.
- [x] Non-destructive `sync-index`: preserve extra columns in tables (such as `Owner` in category tables), preserve existing `Next up` and category row order unless `--reorder` is passed, preserve bare `Id` cell format when the existing index uses it, and ignore companion files (`T###-*.md`) that lack a task header block.
- [x] Per-project header extension fields and `upgrade` exit code: allow `[tasks] extension_fields = ["area", ...]` in `orchestration.toml` or fenced `toml` blocks in `tasks/AGENTS.md`; `upgrade` exits `0` when its own work succeeds and surfaces pre-existing validation issues as warnings.
- [x] Add regression tests in `test_tasks_engine.py` and verify on a temporary copy of `~/works/gcube/porting_liferay/tasks`.
- [x] Bounce fixes (2026-10-25): parse prose `Extra header fields:` declarations in `tasks/AGENTS.md` and document accepted forms in the managed block; omit decider-only blocked/waiting tasks without an explicit question from `Decisions waiting`; honour `short:` headers and hand-curated short labels as `T### (short)` in category tables; add per-section table/Next-up diff summaries in `upgrade`/`sync-index` previews and print `[ok] already in sync, nothing written` when `sync-index --apply` has no changes.

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k "test_t050"`
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/`
- Live check on a scratch copy of `~/works/gcube/porting_liferay/tasks` (`upgrade` preview + `--apply --expect-plan-hash`, `sync-index --apply`, `validate`): 0 `unknown header field(s): area` warnings, no `T038` row in `Decisions waiting`, `T154 (client/model compatibility check)` preserved in category table, per-section preview summary printed, and `[ok] already in sync, nothing written` on subsequent `sync-index --apply`.
- `python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py validate --tasks-dir tasks`
- `python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py sync-index --tasks-dir tasks --check`

## Bounced 2026-10-25 (requester validation, porting-liferay-8c, on a throwaway copy of their tree)

OK: the preview writes nothing and the plan hash works; tasks/AGENTS.md project rules intact, managed block only
appended; Owner column and Id format kept; no companion-file rows; no row lost; sync-index after upgrade idempotent.
NOT OK:
1. **`area` declared in prose is not recognised.** Their tasks/AGENTS.md says ``**Extra header fields: `area`** (free-text
   topic label)``; validate warns 100x "unknown header field(s): area". get_project_extension_fields claims (comment) to
   read "Extra header fields: `area`" but only matches `extension_fields = [...]`. A fenced ```toml [tasks]
   extension_fields = ["area"]``` works. Parse the prose form (with or without bold), or drop the claim and document
   the fence form in the managed block.
2. **Spurious Decisions row.** After upgrade the decisions table gets `| T038 | P2 | Alfredo | Alfredo | - |` (decider
   name in the "Question (exact)" column) for a blocked task with `decider: Alfredo` and no question. Expected: no
   row, or the question text from the body.
3. **`short` ignored in the category tables.** Rows that used the short label (e.g. T154 `- short: client/model
   compatibility check`) become full titles; honour `short` (as elsewhere: `ID (short)` or a short column), or flag it
   in the plan.
4. Minor: the preview summarises only "+94/-67 lines"; give a per-section summary (rows added/removed/changed per
   table, Next up changes). sync-index prints "[ok] updated" even when nothing changed.
Delivery: `~/.local/bin/ai-orch` resolves an older installed plugin copy without --apply/--expect-plan-hash, so T054
and T050 are not live for projects using the launcher until the plugins are released and reinstalled.
Re-ping porting_liferay when fixed; they re-run on the copy.

### Fixed 2026-10-25 (kilo)

1. **Prose declaration of extension fields:** `get_project_extension_fields` now parses prose/bullet declarations ``Extra header fields: `area` `` (with or without bold, one or several backticked field names separated by commas or `and`/`or`), alongside fenced `toml` blocks and `orchestration.toml`. Documented all accepted forms in `MANAGED_TASKS_AGENTS_BLOCK` and `SKILL.md`.
2. **No spurious Decisions rows:** `_extract_task_decision_question` requires an explicit question (either `<who>: <question>` in `decider` where the question differs from the decider name, or an explicit `Question:` / `## Question(s)` in the body, or an open `Q###` question file) and never falls back to putting the decider's name in `Question (exact)`. Blocked/waiting tasks with `decider: Alfredo` and no question (such as `T038`) produce no Decisions row.
3. **Short titles in category tables:** `_format_index_id_cell` honours explicit `short:` headers and hand-curated short labels in `[label](path)` cells by formatting the `Id` cell as `T### (short)` (e.g. `T154 (client/model compatibility check)`) consistently across `Next up`, `Tasks by category`, and `Done`, while keeping bare `T###` IDs for tasks without `short:` in bare-ID indices.
4. **Per-section plan summary and no-change message:** `summarize_index_changes` reports rows added/removed/changed per section and per category table plus `Next up` membership changes in `upgrade` and `sync-index` previews; `sync-index --apply` prints `[ok] already in sync, nothing written` when no changes are needed.

## Log (newest first)

- 2026-10-25, porting_liferay: state `verified` -> `done`
- 2026-10-25, porting_liferay: state `delivered` -> `verified`
- 2026-10-25, kilo: state `bounced` -> `delivered` — KO3 fixed: Id-cell format kept per table; short goes into the Task link text in bare-id tables
- 2026-10-25, porting-liferay-8c: state `delivered` -> `bounced` — Re-check NOT OK on KO3 only: short label placed in the Id cell instead of the Task link text (57 Id cells changed)
- 2026-10-25, kilo: state `bounced` -> `delivered` — Fixed all 4 bounce items, added 5 regression tests, verified on scratch copy of porting_liferay/tasks
- 2026-10-25, porting-liferay-8c: state `delivered` -> `bounced` — Requester validation NOT OK: prose extension_fields not parsed, spurious Decisions row, short titles dropped in category tables (details in the task)

## Re-check 2026-10-25 (porting-liferay-8c, architect-side 0.7.2): one point left

OK: preview writes nothing, per-section summary, AGENTS.md 0 lines removed, KO1 (0 area warnings), KO2 (no T038 Decisions
row), "already in sync" message, no row lost.
NOT OK, KO3: the short label went into the **Id** cell (`| T154 (client/model compatibility check) | … | [full title](…)`),
changing 57 Id cells and breaking lookups like `grep '^| T154 |'`. The project's convention is a bare Id and the short
label as the **Task link text** (`| T154 | P0 | [client/model compatibility check](social-sg4/T154-….md) |`). Fix: keep
the Id cell exactly in the format the table already uses (bare `T###` here), and put `short`, when present, into the
Task link text; never change an existing Id-cell format. (The previous spec suggested the Id-cell form; that was wrong
for tables whose Id column is bare.)

### Fixed 2026-10-25 (kilo), KO3

- `_table_uses_bare_id_format` determines per-table `Id`-cell format from each table's existing rows (falling back to index-level `_index_uses_bare_id_format` for empty or newly created tables, and to `T### (short)` when the index has no `T###` rows).
- When a table uses bare `T###` IDs (`prefer_bare=True`), `_format_index_id_cell` always emits bare `T###` (even when `short:` is present), and `_format_index_task_cell` puts `short` (or an existing hand-curated short label passing `_extract_hand_curated_short_label`) into the `Task` link text `[short](rel_path)` while keeping the full title otherwise.
- When a table uses `T### (short)` IDs (`prefer_bare=False`), `_format_index_id_cell` keeps `T### (short)` in the `Id` cell and `_format_index_task_cell` keeps `[title](rel_path)` as the `Task` link text.
