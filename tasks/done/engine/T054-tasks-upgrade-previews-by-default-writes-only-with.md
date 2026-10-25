# T054 tasks upgrade previews by default; writes only with --apply and a plan hash

- id: T054
- title: tasks upgrade previews by default; writes only with --apply and a plan hash
- category: engine
- priority: P1
- priority-reason: Plain 'upgrade' writes AGENTS.md and the index without a preview, against the preview-then-apply convention; seen while checking T050
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: ai-coding-tools review of T050 (2026-10-25)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T054-tasks-upgrade-previews-by-default-writes-only-with.md, do the open steps, run the Verification, update the task and the registry.
- verifier: ai-coding-tools-c1
- short: Upgrade preview by default

## Goal

'ai-orch tasks upgrade' without --apply prints the plan (files to create or change, with a diff summary) and a plan hash and writes nothing; '--apply --expect-plan-hash H' writes; '--dry-run' and '--preview' stay as aliases of the default; the skill, the managed AGENTS.md block and the help text say so; tests cover no-write by default and apply with a stale hash refused.

## Steps

- [x] Inspect `cmd_upgrade`, `upgrade_tasks_tree`, and CLI argument subparsers in `tasks_engine.py`.
- [x] Update `compute_operation_plan` to carry `summary` in plan output while keeping canonical hash over `(action, before_hash, path)`.
- [x] Modify `upgrade_tasks_tree` to support `apply: bool | None` and `expect_plan_hash`, verifying the plan hash before executing disk modifications and returning `applied: True/False`.
- [x] Update `cmd_upgrade` to preview by default without `--apply`, printing plan diff summaries, plan hash, and `To apply: ai-orch tasks upgrade ...`, and requiring `--apply --expect-plan-hash <hash>` to write.
- [x] Update `is_mutating_command` to consider `upgrade` mutating only when `--apply` is present (and not in preview/dry-run).
- [x] Update help text and documentation in `bin/ai-orch` and `SKILL.md`.
- [x] Update existing upgrade tests to use `--apply --expect-plan-hash` and add `test_t054_upgrade_previews_by_default_and_applies_only_with_plan_hash`.
- [x] Verify live behavior on scratch copy of `porting_liferay/tasks` with clean git status on plain upgrade and expected modifications on apply.

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py` (194 passed)
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_feedback.py` (11 passed)
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/shared/skills/orchestration-setup/scripts/` (all passed)
- Live test on scratch copy of `~/works/gcube/porting_liferay/tasks`:
  - Plain upgrade prints diff summary and plan hash without modifying disk (`git status` clean).
  - Apply without hash refused with code 1 (`git status` clean).
  - Apply with stale hash refused with code 1 (`git status` clean).
  - Apply with plan hash applies modifications cleanly with code 0.

## Log (newest first)

- 2026-10-25, orchestrator: state `verified` -> `done` — Verified by its requester
- 2026-10-25, ai-coding-tools-c1: state `delivered` -> `verified` — Requester check (independent of the executor, kilo): on a scratch copy of porting_liferay/tasks, plain upgrade wrote nothing and printed a hash; --apply without a hash and with a wrong hash were refused; --apply with the hash wrote the 2 files; full suite 558 passed
