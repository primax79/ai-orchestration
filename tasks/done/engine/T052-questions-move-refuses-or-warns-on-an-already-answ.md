# T052 questions move refuses or warns on an already answered question

- id: T052
- title: questions move refuses or warns on an already answered question
- category: engine
- priority: P3
- priority-reason: Minor gap found while validating T041
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N051 (gcube_audit)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T052-questions-move-refuses-or-warns-on-an-already-answ.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Move answered question guard

## Goal

'ai-orch questions move Q###' on a question in status 'answered' refuses with a message saying the answer should be applied (questions apply), unless --force is given; covered by a test.

## Steps

- [x] Add `force: bool = False` (`--force`) to `move_question` and `cmd_questions_move`, refusing `status: answered` questions without `--force`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implemented and verified with automated pytest regression tests
- 2026-10-25, owner: state `delivered` -> `verified` — Implemented and verified with automated pytest regression tests
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
