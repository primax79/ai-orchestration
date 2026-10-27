# Q003 Entrambi i plugin architect-side devono restare abilitati in Claude, o Claude deve mantenerne solo uno

- id: Q003
- question: Entrambi i plugin architect-side devono restare abilitati in Claude, o Claude deve mantenerne solo uno?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A
- applied: yes
- short: Entrambi i plugin architect

## Context

Claude carica architect-side@ai-orchestration (skill generica orchestration-workflow) e architect-side@kilo-mcp (skill associata kilo-mcp-orchestrator); entrambe competono per lo stesso trigger. Disabilitare architect-side@ai-orchestration rimuoverebbe anche altre cinque skill in uso (task-pipeline, task-spec-authoring, task-worktree-ops, conflict-resolver, orchestration-metrics). Fonte: tasks/env-doctor/notes/T016-report.md (studio sul Doctor, 2026-10-17).

## Options

- **A** — Mantenerli entrambi, prendere atto del conflitto: il Doctor lo mostra come riconosciuto, non come errore
- **B** — Preferire la skill generica in Claude: cambiare la policy dei conflitti per Claude in generic
- **C** — Dividere il plugin: spostare orchestration-workflow fuori da architect-side@ai-orchestration in modo da poterla disabilitare singolarmente

## Answer

- choice: open
- answered-by: owner
- answered: 2026-10-17

```text
non mi è chiaro se siano incompatibili in assoluto, o solo nella formulazione corrente
eventualmente, riusciamo a dare priorità tra di loro, o fare modo via prompt di indicare come regolarsi se esistono assieme?
```
