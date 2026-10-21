# T039 Adopting existing trees: legacy plans/, next-id preview, discover before registering

- id: T039
- title: Adopting existing trees: legacy plans/, next-id preview, discover before registering
- category: engine
- priority: P2
- priority-reason: New trees start next to legacy layouts; ids announced before creation collide
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N001, N014, N015
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, scripts/orchestration_registry.py
- handoff: Read tasks/tasks/T039-adopting-existing-trees-legacy-plans-next-id-previ.md, do the open steps, run the Verification, update the task and the registry.
- short: Adoption helpers

## Goal

'tasks upgrade --dry-run' (or a normalize command) proposes moving a legacy plans/NN-*/ macroplan into tasks/; 'tasks new --dry-run' prints the id it would take; 'projects discover <path>' works read-only on an unregistered workspace. Also (inbox N038): validate warns, never fails, on legacy free-text header fields of old tasks. Also (inbox N043): the registry warns about registered projects whose folder is gone, and 'projects discover' prints added/removed projects instead of the whole list.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
