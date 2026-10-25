# UC035 - Architect cleans up merged worktrees and stale sessions safely

- id: UC035
- title: Architect cleans up merged worktrees and stale sessions safely
- actor: Architect session
- status: draft
- priority: P2
- linked-tasks: T012
- verification-type: code-audit
- last-tested: -
- last-verdict: -
- short: Clean up executor debris

## Description & Business Value
Allows the architect session to preview and execute cleanup of merged worktrees, branches, idle sessions, and orphan dev-server processes while preserving any worktree with uncommitted or unmerged leftover work (not implemented yet; spec is DRAFT v0). Source: tasks/specs/executor-housekeeping-and-completion.md §3

## Preconditions
- Parallel executor runs have left behind merged worktrees, branches, or idle sessions.

## Scenario / Interaction Steps
1. The architect invokes cleanup in dry-run mode with a keep-list of active branches/sessions.
2. Any worktree with uncommitted changes or unmerged commits is flagged as leftover_work and kept.
3. Applying the plan with plan_hash removes only clean, merged worktrees/branches and writes an audit record.

## Automated Verification Command
```bash
echo 'manual: Spec executor-housekeeping-and-completion.md is DRAFT v0; verify kilo_cleanup dry-run/apply and tasks validate --branch once implemented.'
```

## Acceptance Criteria
- [ ] Cleanup runs dry-run first and requires a matching `plan_hash` on apply.
- [ ] Worktrees with uncommitted changes (`git status --porcelain` non-empty) or unmerged commits are never deleted and are reported under `leftover_work`.
- [ ] Only merged branches (`git branch -d` semantics, never `-D`) and processes inside removed worktrees are cleaned up, with an audit log written to `.kilo/cleanup-<timestamp>.json`.

## AI Validation Log

