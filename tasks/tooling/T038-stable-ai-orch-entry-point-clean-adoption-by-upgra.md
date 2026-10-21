# T038 Stable ai-orch entry point; clean adoption by upgrade

- id: T038
- title: Stable ai-orch entry point; clean adoption by upgrade
- category: tooling
- priority: P2
- priority-reason: Agents move to the broker MCP (16.6); what remains is the CLI fallback and small fixes
- next-up: no
- state: delivered
- executor: kilo
- depends-on: 16.6
- decider: -
- sources: feedback round 2026-10-21: inbox N003, N010, N011, N012
- paths: bin/ai-orch, scripts/orchestration_env.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tooling/T038-stable-ai-orch-entry-point-clean-adoption-by-upgra.md, do the open steps, run the Verification, update the task and the registry.
- short: Stable entry point

verification pending: run Verification checks (independent verifier)

## Goal

Re-scoped 2026-10-21 (owner): agents reach the engine through the broker MCP (16.6), which also gives the shim a version-free path; this task keeps only the CLI fallback and small fixes. For sessions that work without MCP, 'ai-orch' runs from the same version-free path (documented in the plugin README); running the engine script directly never warns about orchestration_events; 'tasks upgrade' writes tasks/.gitignore with the lock; the Doctor reports vendored copies of tasks_engine.py inside projects as stale.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
