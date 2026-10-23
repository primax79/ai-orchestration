# T042 Waiting-on qualifier for waiting tasks

- id: T042
- title: Waiting-on qualifier for waiting tasks
- category: engine
- priority: P2
- priority-reason: Coordinators cannot tell waiting-on-owner from waiting-on-third-party in the index
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N036 (gcube_audit, N035 consultation)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T042-waiting-on-qualifier-for-waiting-tasks.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Waiting-on qualifier

## Goal

A task in 'waiting' can carry a 'waiting-on' header (owner, team, external, or a free short text), set by the transition or a set command, shown in the index and the UIs and filterable; it is not a new state.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Merged 512a93c; waiting-on qualifier across CLI, 00-INDEX.md, and validation verified (173 passed)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Dispatching T042 (Waiting-on qualifier for waiting tasks) to Kilo
