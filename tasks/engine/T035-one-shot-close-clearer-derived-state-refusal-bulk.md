# T035 One-shot close, clearer derived-state refusal, bulk close of verified

- id: T035
- title: One-shot close, clearer derived-state refusal, bulk close of verified
- category: engine
- priority: P1
- priority-reason: Asked by three sessions (two as top change); closing takes four calls today
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N008, N018, N025, N026
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tasks/T035-one-shot-close-clearer-derived-state-refusal-bulk.md, do the open steps, run the Verification, update the task and the registry.
- short: One-shot close

## Goal

'tasks transition <id> done --verifier X [--reason R]' walks the legal states in one call, runs every guard once and records the same reason/verifier on each step (dry-run first). A refusal on a derived-state parent shows the current derived state and says it closes when its leaves do. A bulk 'tasks close --verified [--dry-run]' closes verified items, and the index counts 'finished, not archived'. Also from the N035 consultation: a one-command self-close for solo repositories ('--self-verified', which records 'done with a caveat: self-verified only' and a PROGRESS line); the close command offers 'done with a caveat' with its reason (a session closed an incident as plain 'done' for lack of it); '--verifier' accepts a session name as a first-class value (e.g. 'gcube-atlas-83').

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
