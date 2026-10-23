# T049 Project discovery: only task trees, no ignored folders or symlinks; ignore config; hide empty projects

- id: T049
- title: Project discovery: only task trees, no ignored folders or symlinks; ignore config; hide empty projects
- category: server-and-bindings
- priority: P1
- priority-reason: porting_liferay's task viewer lists 418 projects, 417 empty: the multi-project view is unusable there
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N048 (porting_liferay)
- paths: ../vscode-ai-orchestration/src/project-resolver.ts, ../vscode-ai-orchestration/src/extension.ts, ../ai-orchestration-ui/backend/projects.py, ../ai-orchestration-ui/frontend/src/components/Navbar.tsx, scripts/orchestration_registry.py
- handoff: Read tasks/server-and-bindings/T049-project-discovery-only-task-trees-no-ignored-folde.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Project discovery hygiene

## Goal

Discovery (VS Code resolver, UI backend, registry discover) proposes only folders that contain tasks/00-INDEX.md, never descends into git-ignored folders, never follows symlinks; a versioned per-workspace config (e.g. [workspace.discovery] include/exclude globs in the workspace's orchestration.toml, or a .ai-orchestration/projects-ignore file) filters further; the selectors hide projects with zero tasks by default with a 'show empty' toggle. The ignore config accepts both project names and paths, where a path ignores a whole folder subtree (e.g. `liferay62/`, `source_codes/`) with everything under it (owner, via porting_liferay). Reproduce first on ~/works/gcube/porting_liferay (read-only) and report the root cause of the 417 entries.

## Steps

- [x] **Root cause analysis on `~/works/gcube/porting_liferay` (read-only):**
  1. `is_git_ignored(path, ws_path)` in all three codebases (`orchestration_registry.py`, `backend/projects.py`, `src/project-resolver.ts`) began with `if (path / ".git").exists(): return False`. Whenever a git-ignored directory in `porting_liferay` (such as `/ansible-playbooks/`, `security_audit/`, `/liferay62/`, `/conductor/`, `/source_codes/`) was itself a nested git clone, `is_git_ignored` returned `False` instead of checking `ws_path`'s `.gitignore`. Once the walker entered that nested git repo, `_git_repo_root(path)` resolved to the inner `.git`, so nothing inside it was ignored by `ws_path/.gitignore` — exposing ~410 Ansible role folders (`roles/<role>/tasks/main.yml`) plus nested repos.
  2. `os.walk(str(ws_path))` in Python includes symlinked directories (`libs-jdk17 -> ~/works/gcube_repos/gcube-jdk17` and `security_audit/private/services -> ~/works/gcube_audit/services`) in `dirs` and called `.resolve()` on them.
  3. `ProjectResolver` in both `backend/projects.py` and `src/project-resolver.ts` cached `_cached_projects` / `_cachedProjects` indefinitely without checking `.gitignore` or ignore config mtimes, and `invalidateTasksCache()` never cleared `_cachedProjects` (keeping stale pre-T048 entries cached in the running VS Code Extension Host even after webview reload).
- [x] Fix `is_git_ignored` across `ai-orchestration/scripts/orchestration_registry.py`, `ai-orchestration-ui/backend/projects.py`, and `vscode-ai-orchestration/src/project-resolver.ts` so named `.gitignore` rules in the workspace or parent repo always exclude nested `.git` directories, while blanket root wildcards (`*` or `/*` in allowlist wrapper workspaces like `ai-coding-tools`) still allow nested repos.
- [x] Refuse symlinks (`is_symlink()` / `isSymbolicLink()`) on folders, `tasks/`, and `tasks/00-INDEX.md`, and require `tasks/00-INDEX.md` across all three discovery implementations.
- [x] Implement `WorkspaceDiscoveryFilter` (`load_workspace_discovery_filter` / `loadWorkspaceDiscoveryFilter`) supporting `.ai-orchestration/projects-ignore`, `.ai-orchignore`, and `[workspace.discovery]` (`include` / `exclude` / `ignore` in `orchestration.toml`), matching both project names/slugs and folder subtrees (e.g. `liferay62/`, `source_codes/`, `porting_liferay_cnr/modules/`) with `!` negation, plus automatic cache invalidation on config/gitignore mtime changes.
- [x] Hide projects with 0 active tasks by default in the Web UI (`Navbar.tsx`) and VS Code `aiOrchestration.selectProject` QuickPick (`extension.ts`), with a `Show empty (+N)` / `Hide empty (N)` toggle.

## Verification

- `pytest scripts/test_orchestration_registry.py` in `ai-orchestration` (12 passed)
- `.venv/bin/pytest backend/test_multi_project.py && npm --prefix frontend run build` in `ai-orchestration-ui` (9 passed, frontend built)
- `npm run sync-webview && npm run compile && node scripts/test-multi-project.mjs` in `vscode-ai-orchestration` (all 6 multi-project test suites passed; compiled `out/extension.js` and `dist-webview/` synced to `~/.vscode/extensions/alfredooliviero.vscode-ai-orchestration-0.6.0/`)
- Read-only check on `~/works/gcube/porting_liferay`, `~/works/d4science-python-library`, and `~/works/ai-coding-tools` across all three resolvers.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
