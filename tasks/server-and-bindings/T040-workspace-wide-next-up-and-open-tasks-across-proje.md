# T040 Workspace-wide next-up and open tasks across projects

- id: T040
- title: Workspace-wide next-up and open tasks across projects
- category: server-and-bindings
- priority: P2
- priority-reason: Most-used command for a multi-repo workspace; today one grep per tasks tree
- next-up: no
- state: in progress
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N030
- paths: scripts/orchestration_registry.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/server-and-bindings/T040-workspace-wide-next-up-and-open-tasks-across-proje.md, do the open steps, run the Verification, update the task and the registry.
- short: Workspace next

## Goal

'ai-orch workspace next [--root P]' lists next-up and open tasks of every project of the workspace (qualified ids, short titles, coordinates expanded), from the same resolver as the UI's common view.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.

## Log (newest first)

- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Dispatching T040 (Workspace-wide next-up and open tasks across projects in one call) to Kilo
