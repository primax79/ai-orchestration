# T051 tasks reopen crashes on emergent tasks (TypeError in _update_index_task_path)

- id: T051
- title: tasks reopen crashes on emergent tasks (TypeError in _update_index_task_path)
- category: engine
- priority: P1
- priority-reason: Reopening is the path for every NOT OK validation; it crashes halfway
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: ai-coding-tools, 2026-10-25, reopening T035/T037
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T051-tasks-reopen-crashes-on-emergent-tasks-typeerror-i.md, do the open steps, run the Verification, update the task and the registry.
- verifier: ai-coding-tools-c1
- short: reopen crash

## Goal

'ai-orch tasks reopen T### --reason R --expect-plan-hash H' on an emergent task in done/ moves it back, sets it open, updates 00-INDEX.md and exits 0. Today it moves the file and sets the state, then crashes with 'TypeError: _update_index_task_path() got multiple values for argument old_rel', leaving the index stale. Add a regression test for reopening an emergent task (single file and folder task).

## Steps

- [x] Fix the call to _update_index_task_path in reopen (duplicate old_rel argument) and handle folder tasks (git mv of the T###-slug folder)
- [x] Regression tests for single-file and folder emergent tasks and for the dry run (test_tasks_engine.py, 10 reopen tests pass)

## Verification

- Live check on a scratch copy of ai-orchestration/tasks: `tasks reopen T034 --reason ... --expect-plan-hash ...` exits 0, the file returns to server-and-bindings/, the index row points to the new path, `validate` and `sync-index --check` are clean (2026-10-25)
- Full suite 552 passed; the one failure (test_t022_cancel_stops_tool_children_in_new_session) passes alone 6/6 and is tracked in T053

## Log (newest first)

- 2026-10-25, orchestrator: state `verified` -> `done` — Verified by its requester
- 2026-10-25, ai-coding-tools-c1: state `delivered` -> `verified` — Requester check (independent of the executor, kilo): live reopen of done T034 on a scratch copy of ai-orchestration/tasks exited 0, file back in its category, index row updated, validate and sync-index --check clean (2026-10-25); 10 reopen tests pass
