# T052 questions move refuses or warns on an already answered question

- id: T052
- title: questions move refuses or warns on an already answered question
- category: engine
- priority: P3
- priority-reason: Minor gap found while validating T041
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N051 (gcube_audit)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T052-questions-move-refuses-or-warns-on-an-already-answ.md, do the open steps, run the Verification, update the task and the registry.
- short: Move answered question guard

## Goal

'ai-orch questions move Q###' on a question in status 'answered' refuses with a message saying the answer should be applied (questions apply), unless --force is given; covered by a test.

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
