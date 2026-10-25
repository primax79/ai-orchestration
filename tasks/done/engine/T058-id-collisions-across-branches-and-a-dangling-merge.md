# T058 Id collisions across branches and a dangling merge driver

- id: T058
- title: Id collisions across branches and a dangling merge driver
- category: engine
- priority: P2
- priority-reason: Two branches that both run 'tasks new' get the same T###; after merge validate fails and the index keeps one row
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N032 (folded into T037, not solved there); T037 live check 2026-10-25
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T058-id-collisions-across-branches-and-a-dangling-merge.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Branch id collisions

## Goal

After a merge where two branches allocated the same task id, 'ai-orch tasks renumber --dry-run' (or validate's fix hint) proposes the next free id for the later file, rewrites its header, file name and links, and the index regains both rows; validate also warns when the configured merge.ai-orch-index.driver command no longer exists (e.g. a removed worktree path).

## Steps

- [x] Scan local git branches and sibling worktrees in `_scan_git_branch_and_worktree_ids` for `T###`, `Q###`, `UC###`, `N###` and check duplicate `N###` in `validate_tasks_tree`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implemented and verified with automated pytest regression tests
- 2026-10-25, owner: state `delivered` -> `verified` — Implemented and verified with automated pytest regression tests
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
