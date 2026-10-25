# T063 reopen can target delivered and set verify-by

- id: T063
- title: reopen can target delivered and set verify-by
- category: engine
- priority: P3
- priority-reason: Fixing a close by the wrong verifier takes four commands and hand edits
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-115656-reopen-can-target-delivered-when-a-task-/note.md
- paths: -
- handoff: Read tasks/engine/T063-reopen-can-target-delivered-and-set-verify-by.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Reopen to delivered

## Goal

Closing a task with the wrong verifier (e.g. architect instead of the requester) needs reopen (-> open) then in-progress then delivered, and verify-by plus the pending line by hand. Proposal: 'reopen <id> --to delivered --verify-by <ws>' clears verifier, sets verify-by and writes the pending line, one Log line.

## Steps

- [x] Add `--to {open,delivered}` and `--verify-by` to `tasks reopen` for one-step reopen to `delivered`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implemented and verified with automated pytest regression tests
- 2026-10-25, owner: state `delivered` -> `verified` — Implemented and verified with automated pytest regression tests
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
