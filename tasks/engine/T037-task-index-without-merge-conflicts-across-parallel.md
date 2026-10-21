# T037 Task index without merge conflicts across parallel branches

- id: T037
- title: Task index without merge conflicts across parallel branches
- category: engine
- priority: P1
- priority-reason: Top change of gcube-audit: every parallel merge conflicts in 00-INDEX.md, with duplicate rows and once a lost answer
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N002
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tasks/T037-task-index-without-merge-conflicts-across-parallel.md, do the open steps, run the Verification, update the task and the registry.
- short: Conflict-free task index

## Goal

Merging two branches that each added tasks never needs a hand-resolved 00-INDEX.md: e.g. a git merge driver registered by 'tasks upgrade' (.gitattributes + local git config) that regenerates the generated regions with sync-index after the merge, or index regions rebuilt on demand. Design first (short spec section, options compared), then implement; question files are never touched by index regeneration.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
