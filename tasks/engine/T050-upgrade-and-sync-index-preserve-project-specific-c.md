# T050 upgrade and sync-index preserve project-specific content; per-project extension fields

- id: T050
- title: upgrade and sync-index preserve project-specific content; per-project extension fields
- category: engine
- priority: P1
- priority-reason: upgrade/sync-index destroy project rules and registry columns; porting_liferay cannot adopt the current engine and warns its sessions not to run them
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N049 (porting_liferay, T124 there)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Read tasks/engine/T050-upgrade-and-sync-index-preserve-project-specific-c.md, do the open steps, run the Verification, update the task and the registry.
- short: Non-destructive upgrade

verification pending: run Verification checks

## Goal

upgrade never replaces an existing tasks/AGENTS.md: it adds or refreshes a managed block between markers and keeps everything else; sync-index rewrites only its generated regions, keeps extra columns a project defined (e.g. Owner) and the project's Next up order unless asked, and never turns companion files into task rows; upgrade exits 0 on success with a clear plan; a per-project config ([tasks] extension_fields in the project's orchestration.toml, or a declaration in tasks/AGENTS.md) lets validate accept project-specific header fields such as 'area'. Verified on a scratch copy of ~/works/gcube/porting_liferay/tasks (read-only on the original): the diff keeps their rules and columns.

## Steps

- [x] Non-destructive `tasks/AGENTS.md` in `upgrade`: wrap managed convention in `<!-- ai-orch:managed begin -->` ... `<!-- ai-orch:managed end -->`, preserving all project-specific content outside markers byte-for-byte; support `--dry-run`/`--preview` and `--apply --expect-hash`.
- [x] Non-destructive `sync-index`: preserve extra columns in tables (such as `Owner` in category tables), preserve existing `Next up` and category row order unless `--reorder` is passed, preserve bare `Id` cell format when the existing index uses it, and ignore companion files (`T###-*.md`) that lack a task header block.
- [x] Per-project header extension fields and `upgrade` exit code: allow `[tasks] extension_fields = ["area", ...]` in `orchestration.toml` or fenced `toml` blocks in `tasks/AGENTS.md`; `upgrade` exits `0` when its own work succeeds and surfaces pre-existing validation issues as warnings.
- [x] Add regression tests in `test_tasks_engine.py` and verify on a temporary copy of `~/works/gcube/porting_liferay/tasks`.

## Verification

- `python3 -m pytest -q plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k "test_t050"`
- `python3 -m pytest -q scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/`
- `python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py validate --tasks-dir tasks`
- `python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py sync-index --tasks-dir tasks --check`
