# T036 Steps and verification authored by command; placeholders rejected

- id: T036
- title: Steps and verification authored by command; placeholders rejected
- category: engine
- priority: P1
- priority-reason: Top change of two sessions; ~40 hand rewrites; placeholder tasks pass validate
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N013, N017
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tasks/T036-steps-and-verification-authored-by-command-placeho.md, do the open steps, run the Verification, update the task and the registry.
- short: Steps by command

verification pending: ~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k "step or placeholder or new"

## Goal

'tasks new' takes repeatable --step and --verification; 'tasks step add|check|uncheck <id> "<text>"' edits the checklist with the usual preview/hash; validate errors (or warns, decided by the spec) on the placeholder lines 'Implement task steps.' / 'Verify task implementation.'.

## Steps

- [x] Add --step and --verification repeatable arguments to tasks new
- [x] Enforce placeholder rejection/warnings in tasks validate
- [x] Add tasks step list, add, check, and uncheck subcommands and register in is_mutating_command
- [x] Add unit tests in test_tasks_engine.py and verify all tests pass

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k "step or placeholder or new"` passes.
