# T049 Project discovery: only task trees, no ignored folders or symlinks; ignore config; hide empty projects

- id: T049
- title: Project discovery: only task trees, no ignored folders or symlinks; ignore config; hide empty projects
- category: server-and-bindings
- priority: P1
- priority-reason: porting_liferay's task viewer lists 418 projects, 417 empty: the multi-project view is unusable there
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N048 (porting_liferay)
- paths: ../vscode-ai-orchestration/src/project-resolver.ts, ../ai-orchestration-ui/backend/projects.py, scripts/orchestration_registry.py
- handoff: Read tasks/server-and-bindings/T049-project-discovery-only-task-trees-no-ignored-folde.md, do the open steps, run the Verification, update the task and the registry.
- short: Project discovery hygiene

## Goal

Discovery (VS Code resolver, UI backend, registry discover) proposes only folders that contain tasks/00-INDEX.md, never descends into git-ignored folders, never follows symlinks; a versioned per-workspace config (e.g. [workspace.discovery] include/exclude globs in the workspace's orchestration.toml, or a .ai-orchestration/projects-ignore file) filters further; the selectors hide projects with zero tasks by default with a 'show empty' toggle. The ignore config accepts both project names and paths, where a path ignores a whole folder subtree (e.g. `liferay62/`, `source_codes/`) with everything under it (owner, via porting_liferay). Reproduce first on ~/works/gcube/porting_liferay (read-only) and report the root cause of the 417 entries.

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
