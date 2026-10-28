# T025 Campo titolo breve per task e domande

- id: T025
- title: Campo titolo breve per task e domande
- category: methodology
- priority: P2
- priority-reason: Richiesta dell'owner del 2026-10-18: i soli ID (T007, 12.16) nella chat degli agenti sono illeggibili
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/methodology/T025-short-title-field-for-tasks-and-questions.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- use-cases: UC001, UC004
- short: Campo titolo breve

## Goal

Ogni task, task di piano e domanda porta un titolo breve di 3-4 parole (campo header, ad es. 'Short: release manager'), generato quando assente, validato dal motore e mostrato dalla UI e da VS Code accanto all'ID; inoltre le skill (task-pipeline, template orchestration-workflow, binding di Kilo, contratto dell'executor) istruiscono gli agenti a citare sempre 'ID (titolo breve)' in chat e nei report.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
