# T038 Stable ai-orch entry point; clean adoption by upgrade

- id: T038
- title: Stable ai-orch entry point; clean adoption by upgrade
- category: tooling
- priority: P2
- priority-reason: Agents move to the broker MCP (16.6); what remains is the CLI fallback and small fixes
- next-up: no
- state: done
- executor: kilo
- depends-on: 16.6
- decider: -
- sources: feedback round 2026-10-21: inbox N003, N010, N011, N012
- paths: bin/ai-orch, scripts/orchestration_env.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tooling/T038-stable-ai-orch-entry-point-clean-adoption-by-upgra.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Stable entry point

## Goal

Re-scoped 2026-10-21 (owner): agents reach the engine through the broker MCP (16.6), which also gives the shim a version-free path; this task keeps only the CLI fallback and small fixes. For sessions that work without MCP, 'ai-orch' runs from the same version-free path (documented in the plugin README); running the engine script directly never warns about orchestration_events; 'tasks upgrade' writes tasks/.gitignore with the lock; the Doctor reports vendored copies of tasks_engine.py inside projects as stale.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
