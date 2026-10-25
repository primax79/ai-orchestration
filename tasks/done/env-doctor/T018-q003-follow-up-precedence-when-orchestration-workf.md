# T018 Q003 follow-up: precedence when orchestration-workflow and the generic orchestration skill coexist

- id: T018
- title: Q003 follow-up: precedence when orchestration-workflow and the generic orchestration skill coexist
- category: env-doctor
- priority: P2
- priority-reason: Owner's open answer to Q003: are they incompatible or only worded so; wants a priority rule or prompt-level guidance
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: claude
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/env-doctor/T018-q003-follow-up-precedence-when-orchestration-workf.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Orchestration skill precedence

## Goal

Compare the two skills, state whether they actually conflict or only overlap in wording, and propose a precedence rule (which one wins when both load) written into both skills, so the Doctor can treat the pair as acknowledged. Decision context: questions/Q003.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
