# T060 sync-index adds rows for initiatives missing from the index

- id: T060
- title: sync-index adds rows for initiatives missing from the index
- category: engine
- priority: P2
- priority-reason: Initiatives silently missing from the registry; dave_agent had to add six rows by hand
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-130216-sync-index-never-adds-rows-for-new-initi/note.md
- paths: -
- handoff: Read tasks/engine/T060-sync-index-adds-rows-for-initiatives-missing-from.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: dave_agent
- short: Initiative rows added

## Goal

In dave_agent (2026-10-25) initiatives 40-45 existed as NN-slug/plan.md, were parsed by 'tasks list' and counted by 'tasks validate' (46 initiatives), but 'tasks sync-index --apply' never added them to the generated initiatives table in 00-INDEX.md: it only refreshed the status of rows already present (17, 20). After adding the six rows by hand inside the ai-orch:generated block, a re-sync kept them and filled in the derived status (e.g. 'in progress (done: 40.1-40.2, 40.11; next: 40.3-40.10)'). Expected: sync-index renders one row per parsed initiative, adding missing ones. Also: without --apply the command only previews, which is easy to miss ('[ok]' style output would help to say 'preview only, not written').

## Steps

- [x] In `render_synced_index` (`tasks_engine.py`), extracted `_format_initiative_status_cell` and updated the `Initiatives` table renderer to preserve existing rows byte-for-byte in their existing order (updating only changed derived status cells) and insert rows for missing parsed initiatives in initiative-number order relative to existing rows while reusing the existing table's column/priority/ID/size format; also ensured missing `## Initiatives` sections are inserted when initiatives exist on disk and fixed `_parse_index_table_rows` for `P`-prefixed initiative priorities.
- [x] In `cmd_sync_index` (`tasks_engine.py`), updated preview output without `--apply` to print the section summary + diff and end with `[preview] nothing written; re-run with --apply to write these changes` when there are changes, and `[ok] already in sync, nothing written (<index_path>)` when nothing would change.

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k "t060 or t037"` -> `3 passed`.
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` -> `229 passed in 170.68s (0:02:50)`.
- `~/.pyenv/shims/python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py sync-index --tasks-dir tasks` -> previews only the `T060` state change (`open` -> `delivered (verify-by: dave_agent)`) in `Tasks by category` (`Initiatives: +0 -0 ~0 row(s)`), leaves existing rows untouched, and ends with `[preview] nothing written; re-run with --apply to write these changes`.

## Log (newest first)

- 2026-10-25, kilo: state `open` -> `delivered` — `render_synced_index` adds missing initiative rows in number order with derived status while preserving existing rows/format; `sync-index` preview ends with `[preview] nothing written; re-run with --apply to write these changes`.
