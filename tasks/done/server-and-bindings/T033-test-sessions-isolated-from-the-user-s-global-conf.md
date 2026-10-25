# T033 Test sessions isolated from the user's global config

- id: T033
- title: Test sessions isolated from the user's global config
- category: server-and-bindings
- priority: P1
- priority-reason: A flaky engine test and five run tests depended on the operator's machine (live broker lock, model mapping)
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: suite failures 2026-10-21
- paths: conftest.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/server-and-bindings/T033-test-sessions-isolated-from-the-user-s-global-conf.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Test config isolation

## Goal

Every pytest session gets a temporary global config with a fixed model mapping, so a broker started by another session or the operator's own mapping cannot change results. Also: the sync-index --adopt preview prints the hash to apply it with. Delivered in 4f1caab and 4a3c4f2; full suite 490 passed.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
