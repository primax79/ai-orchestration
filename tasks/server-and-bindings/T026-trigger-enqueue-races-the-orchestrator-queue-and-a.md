# T026 Trigger enqueue races the orchestrator queue and advances the role cursor too early

- id: T026
- title: Trigger enqueue races the orchestrator queue and advances the role cursor too early
- category: server-and-bindings
- priority: P1
- priority-reason: Found by the Codex review of 2026-10-18: a trigger can overwrite a queued turn and events can be lost
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/server-and-bindings/T026-trigger-enqueue-races-the-orchestrator-queue-and-a.md, do the open steps, run the Verification, update the task and the registry.
- short: Trigger enqueue race

## Goal

orchestration_triggers.py allocates <seq>.json for event_batch turns without the orchestrator lock (it should call the canonical enqueue_turn) and advances the shared role cursor when it merely enqueues a turn, while spec events-and-triggers.md 0c says the cursor advances only after the turn's transcript is persisted. Make triggers enqueue through enqueue_turn under the lock, give trigger scanning its own cursor separate from the role delivery cursor, advance the delivery cursor only after durable turn completion, with tests reproducing the race (concurrent owner enqueue + trigger enqueue) and the lost-event case (turn crashes after the trigger advanced the cursor). Evidence from the review: orchestration_triggers.py:938, :947, :1762; orchestration_orchestrator.py:627, :1372.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
