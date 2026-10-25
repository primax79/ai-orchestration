# T054 tasks upgrade previews by default; writes only with --apply and a plan hash

- id: T054
- title: tasks upgrade previews by default; writes only with --apply and a plan hash
- category: engine
- priority: P1
- priority-reason: Plain 'upgrade' writes AGENTS.md and the index without a preview, against the preview-then-apply convention; seen while checking T050
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: ai-coding-tools review of T050 (2026-10-25)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T054-tasks-upgrade-previews-by-default-writes-only-with.md, do the open steps, run the Verification, update the task and the registry.
- short: Upgrade preview by default

## Goal

'ai-orch tasks upgrade' without --apply prints the plan (files to create or change, with a diff summary) and a plan hash and writes nothing; '--apply --expect-plan-hash H' writes; '--dry-run' and '--preview' stay as aliases of the default; the skill, the managed AGENTS.md block and the help text say so; tests cover no-write by default and apply with a stale hash refused.

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
