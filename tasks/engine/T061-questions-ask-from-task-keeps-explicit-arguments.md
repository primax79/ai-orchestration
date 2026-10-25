# T061 questions ask --from-task keeps explicit arguments

- id: T061
- title: questions ask --from-task keeps explicit arguments
- category: engine
- priority: P2
- priority-reason: Owner questions created with empty options and wrong asker; sessions rewrite them by hand
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-145357-questions-ask-from-task-ignores-question/note.md
- paths: -
- handoff: Read tasks/engine/T061-questions-ask-from-task-keeps-explicit-arguments.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: ai-coding-tools
- short: Ask from task keeps args

## Goal

Repro (2026-10-25, workspace ai-coding-tools): `ai-orch tasks questions ask --tasks-dir tasks --from-task T009 --decider owner --asked-by ai-coding-tools --question '...?' --context '...' --option 'A=...' --option 'B=...' --recommended A --blocks T009`. Result Q001: question and title copied from the legacy decider text, context 'Converted from the legacy decider header ...; context to be completed by the owner', empty Options, recommended '-', asked-by 'owner', open-answer yes. Expected: explicit arguments win over the values derived from the task; derive only what is missing. I rewrote Q001 and Q002 by hand.

## Steps

- [ ] Explicit --question/--context/--option/--recommended/--asked-by win over values derived from the task; derive only what is missing

## Verification

- Test: ask --from-task with all arguments produces exactly them; with none, derives from the legacy decider as today
