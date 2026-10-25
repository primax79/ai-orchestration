# T055 Campaign reports never become categories; sync-index drops vanished categories

- id: T055
- title: Campaign reports never become categories; sync-index drops vanished categories
- category: engine
- priority: P2
- priority-reason: A generated report folder shows up as a task category and survives its deletion
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N055 (ai-coding-tools-2c)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T055-campaign-reports-never-become-categories-sync-inde.md, do the open steps, run the Verification, update the task and the registry.
- verifier: ai-coding-tools-2c
- verify-by: ai-coding-tools
- short: No phantom categories

## Goal

The validation campaign writes its report outside the category namespace (e.g. tasks/_reviews/ or a reserved tasks/reports/ added to RESERVED_DIRS), so sync-index never lists it as a category; sync-index rebuilds the category list from the folders that actually hold tasks, so a deleted category disappears from 00-INDEX.md; tests cover both.

## Steps

- [x] Configure `run_validation_campaign` to output reports to `tasks/_reviews/` and add `"reports"` to `RESERVED_DIRS`.
- [x] Update `render_synced_index` and `merge_index_three_way` in `tasks_engine.py` to build the "Tasks by category" list only from category folders that exist and hold at least one active task.
- [x] Add 4 unit tests in `test_tasks_engine.py` verifying campaign reports go to `_reviews/`, `tasks/reports/` is not a category, emptied or deleted category tables are dropped on sync-index, and sync-index is idempotent.
- [x] Run full pytest suite across `plugins/architect-side/skills/task-pipeline/scripts/` (227 passed).
- [x] Verify `sync-index` preview on this repository drops empty categories and retains `engine` with active tasks.

## Verification

- [x] `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/ -k "test_t055"` (4 passed in 3.57s)
- [x] `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` (227 passed in 154.34s)
- [x] `~/.pyenv/shims/python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py sync-index --tasks-dir tasks` (preview confirms removal of empty category tables and preservation of active category `engine`)

## Log (newest first)

- 2026-10-25, ai-coding-tools-2c: state `verified` -> `done` — requester validation on a scratch copy of the ai-coding-tools workspace tasks/: a file dropped in tasks/reports/ creates no category; sync-index --apply kept all 36 task rows (same ids as the real index), only tooling/investigations sections remain (skills dropped: all done), second sync 'already in sync', validate clean
- 2026-10-25, ai-coding-tools-2c: state `delivered` -> `verified` — requester validation on a scratch copy of the ai-coding-tools workspace tasks/: a file dropped in tasks/reports/ creates no category; sync-index --apply kept all 36 task rows (same ids as the real index), only tooling/investigations sections remain (skills dropped: all done), second sync 'already in sync', validate clean
- 2026-10-25, kilo: state `open` -> `delivered` — Campaign reports written to _reviews, reports added to RESERVED_DIRS, sync-index drops empty categories; 227 tests pass
