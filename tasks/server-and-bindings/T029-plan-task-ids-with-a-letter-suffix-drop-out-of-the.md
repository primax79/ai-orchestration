# T029 Plan task ids with a letter suffix drop out of the index

- id: T029
- title: Plan task ids with a letter suffix drop out of the index
- category: server-and-bindings
- priority: P2
- priority-reason: Forwarded by the Evolution Assurance central session (its T021): ### 06.1b tasks silently vanish from the index and the initiative count
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/server-and-bindings/T029-plan-task-ids-with-a-letter-suffix-drop-out-of-the.md, do the open steps, run the Verification, update the task and the registry.
- short: Letter-suffix plan ids

verification pending: run Verification checks (independent verifier)

## Goal

tasks_engine.py does not parse plan tasks with a letter suffix (### 06.1b - ...); validate only warns about a missing ' - ' separator while the task drops out of the index and the initiative count. Accept NN.Tx ids everywhere ids are parsed (plan blocks, depends-on, transitions, qualified refs) or refuse them with a validate ERROR that names the cause; never drop a block silently.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
