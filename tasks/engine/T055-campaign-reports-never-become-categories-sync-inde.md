# T055 Campaign reports never become categories; sync-index drops vanished categories

- id: T055
- title: Campaign reports never become categories; sync-index drops vanished categories
- category: engine
- priority: P2
- priority-reason: A generated report folder shows up as a task category and survives its deletion
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N055 (ai-coding-tools-2c)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T055-campaign-reports-never-become-categories-sync-inde.md, do the open steps, run the Verification, update the task and the registry.
- short: No phantom categories

## Goal

The validation campaign writes its report outside the category namespace (e.g. tasks/_reviews/ or a reserved tasks/reports/ added to RESERVED_DIRS), so sync-index never lists it as a category; sync-index rebuilds the category list from the folders that actually hold tasks, so a deleted category disappears from 00-INDEX.md; tests cover both.

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
