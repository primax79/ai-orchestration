# N093 projects discover registers git worktrees of another repository

- id: N093
- title: projects discover registers git worktrees of another repository
- kind: bug
- status: ready
- created: 2026-11-16T13:08:01.795061+00:00
- author: smartgears4-migration
- about: orchestration_registry.py discover
- produced: -
- processed-by: -
- short: discover registra worktree

In /Users/Alfredo/works/smartgears4_migration, 'ai-orch projects discover .' proposed and registered dockerized_infra/local_env-T033, -T037, -T038. They are git worktrees of ANOTHER repository (~/works/d4science_local_env, itself a registered workspace): their .git is a file 'gitdir: .../d4science_local_env/.git/worktrees/...'. Discover excludes worktrees of the workspace's own repo but not linked worktrees of other repos, so the same task tree appears several times in the UI. Expected: skip any directory whose .git is a gitdir file pointing to .git/worktrees/ (or to a repo that is already a registered workspace). Second gap: there is no 'projects unregister'; removing the [[workspace.projects]] blocks from orchestration.toml and re-running 'workspace register --apply' does not drop the rows from broker/registry.sqlite, I had to delete them by hand.

---
- Author: smartgears4-migration
- Workspace: /Users/Alfredo/works/smartgears4_migration
- ai-orch: 1.1.0 (2965604)
- Date: 2026-11-16 13:08:01 UTC
