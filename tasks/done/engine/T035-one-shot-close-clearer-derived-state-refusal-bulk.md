# T035 One-shot close, clearer derived-state refusal, bulk close of verified

- id: T035
- title: One-shot close, clearer derived-state refusal, bulk close of verified
- category: engine
- priority: P1
- priority-reason: Asked by three sessions (two as top change); closing takes four calls today
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N008, N018, N025, N026
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tasks/T035-one-shot-close-clearer-derived-state-refusal-bulk.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- verify-by: gcube_audit
- short: One-shot close



## Goal

'tasks transition <id> done --verifier X [--reason R]' walks the legal states in one call, runs every guard once and records the same reason/verifier on each step (dry-run first). A refusal on a derived-state parent shows the current derived state and says it closes when its leaves do. A bulk 'tasks close --verified [--dry-run]' closes verified items, and the index counts 'finished, not archived'. Also from the N035 consultation: a one-command self-close for solo repositories ('--self-verified', which records 'done with a caveat: self-verified only' and a PROGRESS line); the close command offers 'done with a caveat' with its reason (a session closed an incident as plain 'done' for lack of it); '--verifier' accepts a session name as a first-class value (e.g. 'gcube-atlas-83'). Every transition writes a dated line (from, to, actor, verifier, reason) into the task itself: PROGRESS.md for folder tasks, a '## Log' section for single-file tasks, so validations are recorded where the owner reads them (inbox N041, gcube_atlas).

## Steps

- [x] Walk `tasks transition <id> done --verifier X [--reason R]` through legal intermediate states (`in progress -> delivered -> verified -> done`) from any non-terminal state, enforcing the independent-verifier guard and supporting `--dry-run` and `--owner-approved`.
- [x] Add bulk `tasks close --verified [--dry-run] [--expect-plan-hash <hash>]` to preview and close all tasks in `verified` state with a single batch plan hash.
- [x] Normalise state spellings (`in-progress`, `In Progress`, `in_progress`, etc.) on read in `normalize_state`, accept them in `list`, `transition`, and `close`, and emit a warning with the canonical spelling in `validate` without rewriting files on read.
- [x] Record a `## Log` line (or `PROGRESS.md` entry for folder tasks) for every intermediate transition step during `close` and `transition` walks.
- [x] Add unit tests in `test_tasks_engine.py` covering all four reopened points.

## Verification

- [x] Full pytest suite passes (`563 passed`): `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/`.
- [x] Live verification on a scratch `git init` copy of `tasks/` in the OS temp dir reproduces and validates all four `gcube-audit` scenarios (`transition <id> done`, `close --verified`, hyphenated `- state: in-progress` in `list`/`validate`/`close`, and per-step `## Log` lines).

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Reopened points verified in test_tasks_engine.py + scratch repo live check; closure approved by owner
- 2026-10-25, owner: state `delivered` -> `verified` — Reopened points verified in test_tasks_engine.py + scratch repo live check; closure approved by owner
- 2026-10-25, kilo: state `in progress` -> `delivered` — Implemented transition walk to done, bulk close --verified, state spelling normalisation, and per-step Log entries; 563 tests pass
- 2026-10-25, kilo: state `open` -> `in progress`
- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Merged 76391c4 + N041 single-file ## Log recording; 12 new unit tests pass

## Reopened 2026-10-25 (requester validation, gcube-audit)

Works: `tasks close <id> --verifier owner --reason r` from 'in progress' reaches done and writes a Log line.
NOT OK:
1. `tasks transition <id> done --verifier owner --reason r` is refused ("must pass through 'delivered' first" from in
   progress; from delivered the allowed list omits done). The goal promised the one-call walk on `transition` too.
2. `tasks close <id> --verified` (bulk close of verified items) does not exist ("unrecognized arguments").
3. A header `- state: in-progress` (hyphenated, 6 tasks in their tree) is not normalised: close and transition refuse
   it, and list shows canonical_state 'in-progress'. Normalise state spellings on read (and offer a fix in validate).
4. The Log records only the last step (verified -> done), not each intermediate step.
Verify again with the requester before closing.
