# N049 upgrade and sync-index destroy project-specific content; validate rejects allowed extra fields

- id: N049
- title: upgrade and sync-index destroy project-specific content; validate rejects allowed extra fields
- kind: bug
- status: processed
- created: 2026-10-21T14:31:22.971407+00:00
- author: porting_liferay
- about: tasks_engine.py upgrade, sync-index, validate
- produced: T050
- processed-by: ai-coding-tools

Dry run of 'tasks upgrade' on a scratch copy of porting_liferay tasks/: (1) overwrites tasks/AGENTS.md with CANONICAL_TASKS_AGENTS_MD (58 -> 20 lines), dropping project rules (priority criteria, categories, git/Redmine rules, the 'area' extra field); should merge or append a managed block. (2) rewrites 00-INDEX.md: drops their 'Owner' column, reorders Next up by its own sort, changes Id cells to 'T037 (short)', misparses a companion file (audit-auth/T101-answers.md) into an empty row. (3) exits rc=1. (4) validate FAILs every task with the 'area' extra field allowed by their tasks/AGENTS.md: needs a per-project config of allowed extension fields. They applied by hand only tasks/.gitignore, tasks/.gitattributes (merge=ai-orch-index) and a Tools section, and warn not to run upgrade or sync-index --apply on that tree until fixed. Tracked there as porting_liferay T124.
