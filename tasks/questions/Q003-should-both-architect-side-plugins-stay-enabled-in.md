# Q003 Should both architect-side plugins stay enabled in Claude, or should Claude keep only one

- id: Q003
- question: Should both architect-side plugins stay enabled in Claude, or should Claude keep only one?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A

## Context

Claude loads architect-side@ai-orchestration (generic orchestration-workflow) and architect-side@kilo-mcp (bound kilo-mcp-orchestrator); they compete for the same trigger. Disabling architect-side@ai-orchestration would also remove five other skills you use (task-pipeline, task-spec-authoring, task-worktree-ops, conflict-resolver, orchestration-metrics). Source: tasks/env-doctor/notes/T016-report.md (Doctor study, 2026-10-17).

## Options

- **A** — Keep both, acknowledge the conflict: the Doctor shows it as acknowledged, not as an error
- **B** — Prefer the generic skill in Claude: change the conflict policy for Claude to generic
- **C** — Split the plugin: move orchestration-workflow out of architect-side@ai-orchestration so it can be disabled alone

## Answer

- choice: open
- answered-by: owner
- answered: 2026-10-17

```text
non mi è chiaro se siano incompatibili in assoluto, o solo nella formulazione corrente
eventualmente, riusciamo a dare priorità tra di loro, o fare modo via prompt di indicare come regolarsi se esistono assieme?
```
