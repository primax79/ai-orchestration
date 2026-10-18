# T024 Confirm or reject trigger-proposed actions (engine + UI wiring)

- id: T024
- title: Confirm or reject trigger-proposed actions (engine + UI wiring)
- category: server-and-bindings
- priority: P2
- priority-reason: E3 turns unattended mutating actions into proposals; today they can only be listed
- next-up: no
- state: in progress
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/orchestration_triggers.py, ../ai-orchestration-ui/backend/server.py
- handoff: Read tasks/server-and-bindings/T024-confirm-or-reject-trigger-proposed-actions-engine.md, do the open steps, run the Verification, update the task and the registry.

## Goal

Add ai-orch triggers confirm ACTION_ID --expect-hash H and triggers reject ACTION_ID --reason R: confirm executes the proposed command/run through the same paths as an owner action (run start with plan hash for runs), records the outcome and emits events; reject records the reason. Then wire the UI endpoints (12.6 left them as list-only) and the VS Code handlers.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
