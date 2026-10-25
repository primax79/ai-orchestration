# T030 conditions: header for tasks done with open questions that may change the result

- id: T030
- title: conditions: header for tasks done with open questions that may change the result
- category: server-and-bindings
- priority: P2
- priority-reason: Forwarded by the Evolution Assurance central session (its T023, owner decision Q005, method docs/08 §7.15)
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/server-and-bindings/T030-conditions-header-for-tasks-done-with-open-questio.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Conditional done

## Goal

A conditions: header (open question ids whose answer may change a finished result; distinct from blocks:): validate checks each id exists; sync-index renders a 'Conditional' section above Done listing such tasks as 'done, conditional (Qnnn)'; when every condition is answered the marker disappears; an answer that changes the result opens a follow-up task. UI (ai-orchestration-ui, VS Code): distinct badge and a KPI counter.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
