# T037 Task index without merge conflicts across parallel branches

- id: T037
- title: Task index without merge conflicts across parallel branches
- category: engine
- priority: P1
- priority-reason: Top change of gcube-audit: every parallel merge conflicts in 00-INDEX.md, with duplicate rows and once a lost answer
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N002
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Read tasks/tasks/T037-task-index-without-merge-conflicts-across-parallel.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- verify-by: gcube_audit
- short: Conflict-free task index

verification pending: re-run your two-branch merge scenario from the 'Reopened 2026-10-25' section on a scratch copy of your tree, with ai-orch >= architect-side 0.7.3: run `upgrade` (preview, then --apply --expect-plan-hash) so it registers the merge=ai-orch-index driver, then create one task on each of two branches and merge; expect no conflict in 00-INDEX.md, both rows kept, validate clean. Same-id collisions are tracked in T058, not here (verify-by: gcube_audit)

## Goal

Merging two branches that each added tasks never needs a hand-resolved 00-INDEX.md: e.g. a git merge driver registered by 'tasks upgrade' (.gitattributes + local git config) that regenerates the generated regions with sync-index after the merge, or index regions rebuilt on demand. Design first (short spec section, options compared), then implement; question files are never touched by index regeneration. Also (inbox N037): a delegated task is registered in the shared tree (row visible, state in progress) before the run starts, not only at merge. sync-index rebuilds generated tables from headers, so duplicate rows left by a merge disappear (inbox N040, gcube_audit; seen with a vendored copy, check current behaviour first).

## Steps

- [x] Register `merge.ai-orch-index.driver` and `merge.ai-orch-index.name` in local git config during `upgrade` (shown in plan preview and applied with `--apply --expect-plan-hash`), warn in `validate` when `.gitattributes` names `merge=ai-orch-index` without the git config driver, and document the setup in `task-pipeline/SKILL.md`.
- [x] Implement 3-way row-level table merge + non-generated 3-way text merge in `merge_index_three_way` / `cmd_merge_index` (`%O %A %B`).
- [x] Print the dry-run footer `"preview only, nothing written; re-run with --apply"` in `sync-index` without `--apply`.

## Verification

- [x] Unit and integration tests in `test_tasks_engine.py` pass (`209 passed`).
- [x] Live check in a scratch git repo under the OS temp dir with two branches adding tasks and running `sync-index --apply` merges cleanly with zero conflicts, both rows present, and zero duplicates.

## Log (newest first)

- 2026-10-25, kilo: state `open` -> `delivered` — Fixed reopen findings: `upgrade` registers `merge.ai-orch-index.driver` and `merge.ai-orch-index.name` in local git config (and shows it in the plan), `validate` warns when `.gitattributes` has `merge=ai-orch-index` without the git config driver, `merge-index %O %A %B` performs a 3-way row-level union merge of generated tables and 3-way text merge outside generated regions, and `sync-index` without `--apply` prints the dry-run footer (209 passed)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Merged d70d453; conflict-free 00-INDEX.md, merge-index driver, and tasks/.gitattributes on upgrade verified (169 passed)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Dispatching T037 (Conflict-free index across parallel worktrees) to Kilo

## Reopened 2026-10-25 (requester validation, gcube-audit)

Setup: two branches each add one valid task + `sync-index --apply`; tasks/.gitattributes has `00-INDEX.md merge=ai-orch-index`.
NOT OK:
1. Nothing sets the git config `merge.ai-orch-index.driver` and no doc mentions it, so the merge still CONFLICTs.
   `upgrade` writes only .gitattributes. Register the driver (upgrade, with preview; or document a one-line setup)
   and make `validate` warn when .gitattributes names the driver but git config lacks it.
2. With the driver configured by hand (`ai-orch tasks merge-index %O %A %B`) the merge has no conflict but drops
   theirs' row (only ours' row kept); a later `sync-index --apply` restores it. The driver must regenerate from the
   merged headers, not keep one side.
OK: duplicate rows are collapsed by `sync-index --apply`.
Minor: `sync-index` without `--apply` prints the whole index as a dry run; easy to mistake for "done". Print a one-line
"preview only, nothing written; re-run with --apply" footer.
Verify again with the requester before closing.
