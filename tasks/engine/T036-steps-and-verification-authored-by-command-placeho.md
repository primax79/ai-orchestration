# T036 Steps and verification authored by command; placeholders rejected

- id: T036
- title: Steps and verification authored by command; placeholders rejected
- category: engine
- priority: P1
- priority-reason: Top change of two sessions; ~40 hand rewrites; placeholder tasks pass validate
- next-up: no
- state: in progress
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N013, N017
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/tasks/T036-steps-and-verification-authored-by-command-placeho.md, do the open steps, run the Verification, update the task and the registry.
- short: Steps by command

## Goal

'tasks new' takes repeatable --step and --verification; 'tasks step add|check|uncheck <id> "<text>"' edits the checklist with the usual preview/hash; validate errors (or warns, decided by the spec) on the placeholder lines 'Implement task steps.' / 'Verify task implementation.'.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.

## Log (newest first)

- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Dispatching T036 (Steps by command, --step/--verification on tasks new, placeholder rejection in validate) to Kilo
