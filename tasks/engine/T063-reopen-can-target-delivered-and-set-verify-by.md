# T063 reopen can target delivered and set verify-by

- id: T063
- title: reopen can target delivered and set verify-by
- category: engine
- priority: P3
- priority-reason: Fixing a close by the wrong verifier takes four commands and hand edits
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-115656-reopen-can-target-delivered-when-a-task-/note.md
- paths: -
- handoff: Read tasks/engine/T063-reopen-can-target-delivered-and-set-verify-by.md, do the open steps, run the Verification, update the task and the registry.
- short: Reopen to delivered

## Goal

Closing a task with the wrong verifier (e.g. architect instead of the requester) needs reopen (-> open) then in-progress then delivered, and verify-by plus the pending line by hand. Proposal: 'reopen <id> --to delivered --verify-by <ws>' clears verifier, sets verify-by and writes the pending line, one Log line.

## Steps

- [ ] reopen <id> --to delivered --verify-by <ws>: clears verifier, sets verify-by, writes the pending line, one Log line

## Verification

- Test: done task reopened to delivered with verify-by; header, pending line and Log as expected
