# T027 Stale-claim recovery relaunches a turn whose child process has not written its pid yet

- id: T027
- title: Stale-claim recovery relaunches a turn whose child process has not written its pid yet
- category: server-and-bindings
- priority: P1
- priority-reason: Gemini review 2026-10-18: violates 'never two resumptions of the same session at the same time'
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/server-and-bindings/T027-stale-claim-recovery-relaunches-a-turn-whose-child.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Duplicate turn resumption

## Goal

run_next_turn claims a turn, releases the orchestrator lock, and the pid is written only after the child starts; a concurrent run-next sees pid=None and treats the claim as crashed (orchestration_orchestrator.py:1034-1052, :1112, :1186-1193), requeueing and launching a second resumption. Respect lease_expires_at and a startup grace period before recovering a claim with no pid; add a test that runs two drains concurrently against a slow-starting stub and asserts a single resumption.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
