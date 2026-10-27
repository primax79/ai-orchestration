# T064 env doctor recognizes identical per-assistant skill copies across ~/.claude/skills and ~/.kilo/skills as intentional

- id: T064
- title: env doctor recognizes identical per-assistant skill copies across ~/.claude/skills and ~/.kilo/skills as intentional
- category: env-doctor
- priority: P2
- priority-reason: 6 false-positive duplicate findings on paired Claude/Kilo standalone skills
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-170336-env-doctor-flags-per-assistant-skill-cop/note.md
- paths: -
- handoff: Read tasks/env-doctor/T064-env-doctor-recognizes-identical-per-assistant-skil.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: env doctor recognizes identical

## Goal

Owner report 2026-10-25 (screenshot of the doctor UI): ADVICE 'duplicate-name: orchestration-metrics / orchestration-setup / pdf / task-pipeline / task-spec-authoring ...: duplicate standalone skill across origins (standalone:~/.claude/skills, standalone:~/.kilo/skills): review and remove one manually'. Owner: these are not duplicates.

## Steps

- [x] Skip `duplicate-name` in `orchestration_env.py` when standalone entries in the same scope have at most one copy per assistant root family and equivalent content.

## Verification

- [x] `pytest scripts/test_orchestration_env.py -k test_n063`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implemented and verified with automated pytest regression tests
- 2026-10-25, owner: state `delivered` -> `verified` — Implemented and verified with automated pytest regression tests
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
