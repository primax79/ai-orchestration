# T041 Questions: unapplied answers surfaced, moved-to-tracker status, Notes section

- id: T041
- title: Questions: unapplied answers surfaced, moved-to-tracker status, Notes section
- category: engine
- priority: P1
- priority-reason: Answered questions stayed unapplied for two days unseen (top change of evolution-assurance)
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: ai-orchestration inbox N009, N016, N019, N020
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tasks/T041-questions-unapplied-answers-surfaced-moved-to-trac.md, do the open steps, run the Verification, update the task and the registry.
- short: Question workflow gaps

## Goal

validate and sync-index warn about answered-but-unapplied questions and the index shows them; 'questions answer' can apply in the same call (--apply-ref, --note); a 'moved' status with an external link for questions turned into tracker issues; an optional free 'Notes' section in question files; the docs present '--blocks -' as the way to ask a non-blocking question.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
