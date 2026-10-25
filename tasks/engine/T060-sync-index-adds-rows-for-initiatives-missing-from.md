# T060 sync-index adds rows for initiatives missing from the index

- id: T060
- title: sync-index adds rows for initiatives missing from the index
- category: engine
- priority: P2
- priority-reason: Initiatives silently missing from the registry; dave_agent had to add six rows by hand
- next-up: no
- state: open
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

- [ ] sync-index renders one Initiatives row per parsed initiative, adding missing rows inside the generated block, keeping existing row format
- [ ] Preview output says clearly 'preview only, nothing written; re-run with --apply'

## Verification

- Test: three initiatives, index lists one; sync-index --apply adds two rows; re-run says already in sync; preview message asserted
