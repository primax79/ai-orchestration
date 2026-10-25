# T051 tasks reopen crashes on emergent tasks (TypeError in _update_index_task_path)

- id: T051
- title: tasks reopen crashes on emergent tasks (TypeError in _update_index_task_path)
- category: engine
- priority: P1
- priority-reason: Reopening is the path for every NOT OK validation; it crashes halfway
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: ai-coding-tools, 2026-10-25, reopening T035/T037
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T051-tasks-reopen-crashes-on-emergent-tasks-typeerror-i.md, do the open steps, run the Verification, update the task and the registry.
- short: reopen crash

## Goal

'ai-orch tasks reopen T### --reason R --expect-plan-hash H' on an emergent task in done/ moves it back, sets it open, updates 00-INDEX.md and exits 0. Today it moves the file and sets the state, then crashes with 'TypeError: _update_index_task_path() got multiple values for argument old_rel', leaving the index stale. Add a regression test for reopening an emergent task (single file and folder task).

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
