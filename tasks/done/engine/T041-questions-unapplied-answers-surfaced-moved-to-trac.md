# T041 Questions: unapplied answers surfaced, moved-to-tracker status, Notes section

- id: T041
- title: Questions: unapplied answers surfaced, moved-to-tracker status, Notes section
- category: engine
- priority: P1
- priority-reason: Answered questions stayed unapplied for two days unseen (top change of evolution-assurance)
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: ai-orchestration inbox N009, N016, N019, N020
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tasks/T041-questions-unapplied-answers-surfaced-moved-to-trac.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Question workflow gaps

## Goal

validate and sync-index warn about answered-but-unapplied questions and the index shows them; 'questions answer' can apply in the same call (--apply-ref, --note); a 'moved' status with an external link for questions turned into tracker issues; an optional free 'Notes' section in question files; the docs present '--blocks -' as the way to ask a non-blocking question.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Merged 29f852c; unapplied answers surfaced, questions move, non-blocking --blocks -, and ## Notes verified (163 passed)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Dispatching T041 (Questions lifecycle: unapplied answers, move-to-tracker, non-blocking, Notes section) to Kilo

## Validation by the requester (2026-10-25)

OK from gcube-audit: `questions move ... --to <url>` gives status moved and shows in `questions list`; `questions list` prints the answered-but-unapplied notice and `validate` warns per question. Minor gap filed as T052.
