# N095 Custom task states per workspace (project-level configuration)

- id: N095
- title: Custom task states per workspace (project-level configuration)
- kind: feature
- status: processed
- created: 2026-11-19T17:09:45.607642+00:00
- author: porting-liferay
- about: tasks_engine.py CANONICAL_STATES
- produced: T092
- processed-by: claude (ai-orchestration maintainer session, 2026-11-19)

## Request

Support custom task states per workspace (project-level configuration), so that a project can add states without
changing `tasks_engine.py`.

## Why

`CANONICAL_STATES`, `TERMINAL_STATES` and `ALLOWED_TRANSITIONS` are hard-coded. Projects with their own lifecycle
(e.g. porting_liferay needed a "tracked on Redmine" state, see the urgent companion request) must either misuse an
existing state or wait for an engine release. A per-workspace extension keeps the canonical set small and lets projects
evolve.

## Expected behaviour

- A project setting (e.g. in the `## Project settings` TOML block of `tasks/AGENTS.md`, or `tasks/states.toml`) declares
  extra states with: name, `maps-to` (the canonical state used for derivation/counting, e.g. `waiting`), terminal yes/no,
  allowed transitions in and out, optional registry section/label and language label.
- `normalize_state`, `is_valid_state`, transitions, container derivation, `validate`, `sync-index` and the UI read the
  merged set (canonical + project).
- Unknown states keep failing validation; a custom state cannot redefine a canonical one.
- Documented in the skill (`SKILL.md` States) and in the template.

## Context

- Requested by porting_liferay (owner Alfredo, 2026-11-19), together with the urgent `tracked` state request.
- The analyzed note `20261021-081656-cross-workspace-executor-and-depends-on-` mentions custom states as considered
  less valuable then; this request is the concrete case.

---
- Author: porting-liferay
- Workspace: /Users/Alfredo/works/gcube/porting_liferay
- ai-orch: 1.1.0 (2965604)
- Date: 2026-11-19 17:09:45 UTC
