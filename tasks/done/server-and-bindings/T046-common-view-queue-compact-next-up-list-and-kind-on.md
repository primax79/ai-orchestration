# T046 Common view Queue: compact next-up list and kind on rows

- id: T046
- title: Common view Queue: compact next-up list and kind on rows
- category: server-and-bindings
- priority: P3
- priority-reason: Usability: 41 cards in the All-projects queue
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N044 (d4science-python-library validation of 16.9)
- paths: ../ai-orchestration-ui/frontend/src
- handoff: Read tasks/server-and-bindings/T046-common-view-queue-compact-next-up-list-and-kind-on.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Compact common queue

## Goal

In the All-projects view the Queue shows a compact next-up list (like the project view, a few items per project or overall) with a link to the full list, and backlog rows show the task kind.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
