# T057 L'avanzamento di transizione attribuisce ogni passo all'attore corretto

- id: T057
- title: L'avanzamento di transizione attribuisce ogni passo all'attore corretto
- category: engine
- priority: P2
- priority-reason: Il Log è il registro dell'indipendenza; l'avanzamento automatico mostra il verificatore come autore della consegna
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N057 (ai-coding-tools, closing T056)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T057-transition-walk-attributes-each-step-to-the-right.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- short: Attribuzione passi transizione

## Goal

In un avanzamento 'transition ... done --verifier V', le righe di Log per i passi fino a delivered indicano l'executor del task (oppure 'recorded by <actor> for <executor>'), mentre solo verified/done indicano il verificatore; il motivo viene scritto una sola volta sui passi del verificatore; coperto da un test.

## Steps

- [x] Attribuire i passi intermedi dell'avanzamento (`in progress`, `delivered`) in `close_task` all'executor del task senza verificatore/motivo.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
