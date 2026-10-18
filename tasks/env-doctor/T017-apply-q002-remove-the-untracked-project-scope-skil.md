# T017 Apply Q002: remove the untracked project-scope skill copies in ai-orchestration

- id: T017
- title: Apply Q002: remove the untracked project-scope skill copies in ai-orchestration
- category: env-doctor
- priority: P2
- priority-reason: Owner answered Q002 with A; the stale copies shadow the released skills in this repo
- next-up: no
- state: delivered
- executor: claude
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/env-doctor/T017-apply-q002-remove-the-untracked-project-scope-skil.md, do the open steps, run the Verification, update the task and the registry.
- short: Remove project skill copies

verification pending: run Verification checks (independent verifier)

## Goal

Delete the untracked skill copies under .claude/skills, .codex/skills and .kilo/skills of the ai-orchestration repo (never .kilo/worktrees or anything tracked), after listing them; they are reproducible from the source plugins. Decision: questions/Q002.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
