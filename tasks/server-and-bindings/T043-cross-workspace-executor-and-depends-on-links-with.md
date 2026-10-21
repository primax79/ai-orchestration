# T043 Cross-workspace executor and depends-on links with live state

- id: T043
- title: Cross-workspace executor and depends-on links with live state
- category: server-and-bindings
- priority: P2
- priority-reason: Work done in another workspace is tracked by hand; sessions value it above custom states
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N039 (d4science-evolution-assurance, N035 consultation)
- paths: scripts/orchestration_registry.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/server-and-bindings/T043-cross-workspace-executor-and-depends-on-links-with.md, do the open steps, run the Verification, update the task and the registry.
- short: Cross-workspace task links

verification pending: run Verification checks (independent verifier)

## Goal

'executor: <workspace>:T030' and cross-workspace depends-on resolve through the workspace registry and show the remote task's live state in validate, the index and the UIs, read-only, like coordinates inside a workspace (16.4).

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.

## Log (newest first)

- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Merged eddaeb5; cross-workspace executor and depends-on links with live target status verified (180 passed)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Dispatching T043 (Cross-workspace executor and depends-on links with live target status) to Kilo
