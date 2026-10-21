# T050 upgrade and sync-index preserve project-specific content; per-project extension fields

- id: T050
- title: upgrade and sync-index preserve project-specific content; per-project extension fields
- category: engine
- priority: P1
- priority-reason: upgrade/sync-index destroy project rules and registry columns; porting_liferay cannot adopt the current engine and warns its sessions not to run them
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N049 (porting_liferay, T124 there)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T050-upgrade-and-sync-index-preserve-project-specific-c.md, do the open steps, run the Verification, update the task and the registry.
- short: Non-destructive upgrade

## Goal

upgrade never replaces an existing tasks/AGENTS.md: it adds or refreshes a managed block between markers and keeps everything else; sync-index rewrites only its generated regions, keeps extra columns a project defined (e.g. Owner) and the project's Next up order unless asked, and never turns companion files into task rows; upgrade exits 0 on success with a clear plan; a per-project config ([tasks] extension_fields in the project's orchestration.toml, or a declaration in tasks/AGENTS.md) lets validate accept project-specific header fields such as 'area'. Verified on a scratch copy of ~/works/gcube/porting_liferay/tasks (read-only on the original): the diff keeps their rules and columns.

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
