# T038 Stable ai-orch entry point; clean adoption by upgrade

- id: T038
- title: Stable ai-orch entry point; clean adoption by upgrade
- category: tooling
- priority: P1
- priority-reason: Sessions run tasks_engine.py from a versioned plugin-cache path or a vendored copy, which breaks on update and misses fixes (suffixed ids)
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N003, N010, N011, N012
- paths: bin/ai-orch, scripts/orchestration_env.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tooling/T038-stable-ai-orch-entry-point-clean-adoption-by-upgra.md, do the open steps, run the Verification, update the task and the registry.
- short: Stable entry point

## Goal

Every session can run 'ai-orch' from a version-free path (installer or setup adds it to PATH, or a stable shim), the plugin README says so, running the engine script directly never warns about orchestration_events, and 'tasks upgrade' writes tasks/.gitignore with the lock. Vendored copies are detected by the Doctor and reported as stale.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
