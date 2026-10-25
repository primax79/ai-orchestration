# UC004 - Architect creates a full emergent task with validated header and steps

- id: UC004
- title: Architect creates a full emergent task with validated header and steps
- actor: Architect session
- status: draft
- priority: P1
- linked-tasks: 02.1, 03.2, T025, T036
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Create emergent task

## Description & Business Value
Allows an architect session to create a standalone emergent task with the 13 mandatory header fields in canonical order and concrete Goal, Steps, and Verification sections, validated by the engine without placeholder warnings. Source: tasks/specs/task-and-state-model.md §2

## Preconditions
- A valid tasks/ tree exists on disk.

## Scenario / Interaction Steps
1. The architect runs ai-orch tasks new with category, title, short title, priority, executor, goal, steps, and verification items.
2. The engine reserves the next globally unique T### id under the task write lock and creates tasks/<category>/T###-<slug>.md.
3. Running ai-orch tasks validate confirms zero header, ordering, or placeholder errors.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(~/.local/bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ~/.local/bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && ~/.local/bin/ai-orch tasks new --tasks-dir "$T/tasks" --category engine --title "Implement parser" --short "Implement parser" --priority P1 --priority-reason "Core need" --executor kilo --goal "Parse task headers" --step "Write parser" --verification "pytest" >/dev/null && ~/.local/bin/ai-orch tasks validate --tasks-dir "$T/tasks" --json | jq -e ".ok == true and (.errors | length == 0)" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Created task file contains all 13 mandatory header fields in canonical order (`id`, `title`, `category`, `priority`, `priority-reason`, `next-up`, `state`, `executor`, `depends-on`, `decider`, `sources`, `paths`, `handoff`).
- [ ] Optional `short` field is stored after `handoff` (or deterministically derived when omitted) and respects the 1-5 words, <=40 chars rule.
- [ ] Body includes `## Goal`, `## Steps`, and `## Verification` sections populated from `--goal`, `--step`, and `--verification` flags without template placeholders.

## AI Validation Log

