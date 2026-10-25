# T060 sync-index adds rows for initiatives missing from the index

- id: T060
- title: sync-index adds rows for initiatives missing from the index
- category: engine
- priority: P2
- priority-reason: Initiatives silently missing from the registry; dave_agent had to add six rows by hand
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-130216-sync-index-never-adds-rows-for-new-initi/note.md; _inbox/analyzed/20261025-160659-sync-index-inserts-a-duplicate-specs-hea/note.md
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py
- handoff: Read tasks/engine/T060-sync-index-adds-rows-for-initiatives-missing-from.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- verify-by: dave_agent
- short: Initiative rows added

## Goal

In dave_agent (2026-10-25) initiatives 40-45 existed as NN-slug/plan.md, were parsed by 'tasks list' and counted by 'tasks validate' (46 initiatives), but 'tasks sync-index --apply' never added them to the generated initiatives table in 00-INDEX.md: it only refreshed the status of rows already present (17, 20). After adding the six rows by hand inside the ai-orch:generated block, a re-sync kept them and filled in the derived status (e.g. 'in progress (done: 40.1-40.2, 40.11; next: 40.3-40.10)'). Expected: sync-index renders one row per parsed initiative, adding missing ones. Also: without --apply the command only previews, which is easy to miss ('[ok]' style output would help to say 'preview only, not written').

## Steps

- [x] Add missing active initiatives in `render_synced_index`, fix unmarked `## Specs` duplicate heading (`N062`), and print preview notice when `--apply` is omitted.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t060`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implemented and verified with automated pytest regression tests
- 2026-10-25, owner: state `delivered` -> `verified` — Implemented and verified with automated pytest regression tests
- 2026-10-25, kilo: state `open` -> `delivered` — `render_synced_index` adds missing initiative rows in number order with derived status while preserving existing rows/format; `sync-index` preview ends with `[preview] nothing written; re-run with --apply to write these changes`.
