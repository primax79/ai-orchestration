# T063 reopen può avere come destinazione delivered e impostare verify-by

- id: T063
- title: reopen può avere come destinazione delivered e impostare verify-by
- category: engine
- priority: P3
- priority-reason: Correggere una chiusura effettuata dal verificatore sbagliato richiede quattro comandi e modifiche manuali
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-115656-reopen-can-target-delivered-when-a-task-/note.md
- paths: -
- handoff: Leggi tasks/engine/T063-reopen-can-target-delivered-and-set-verify-by.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- short: Reopen verso delivered

## Goal

Chiudere un task con il verificatore sbagliato (ad es. l'architect invece del richiedente) richiede reopen (-> open), poi in-progress, poi delivered, più verify-by e la riga pending aggiunti a mano. Proposta: 'reopen <id> --to delivered --verify-by <ws>' azzera verifier, imposta verify-by e scrive la riga pending, con una sola riga di Log.

## Steps

- [x] Aggiungere `--to {open,delivered}` e `--verify-by` a `tasks reopen` per la riapertura in un solo passo verso `delivered`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
