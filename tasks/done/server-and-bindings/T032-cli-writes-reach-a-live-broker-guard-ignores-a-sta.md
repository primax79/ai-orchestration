# T032 CLI writes reach a live broker; guard ignores a stale manifest

- id: T032
- title: CLI writes reach a live broker; guard ignores a stale manifest
- category: server-and-bindings
- priority: P1
- priority-reason: Once a broker runs, every session without the broker MCP tools (evolution-assurance, gcube-audit) cannot write tasks at all
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: message from d4science-evolution-assurance-37, 2026-10-21; broker guard of 16.2
- paths: scripts/orchestration_broker_lock.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, bin/ai-orch
- handoff: Read tasks/server-and-bindings/T032-cli-writes-reach-a-live-broker-guard-ignores-a-sta.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: CLI writes through broker

## Goal

While a live broker holds broker.lock, a mutating ai-orch CLI command forwards the write to it (stdio shim or local HTTP with the UI token) and returns the broker's result, instead of failing with broker-owns-writes. The guard treats a lock as held only when the manifest pid is alive, and its message never cites a dead pid from a stale broker.json. No session ever needs AI_ORCH_BROKER_CHILD to write.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
