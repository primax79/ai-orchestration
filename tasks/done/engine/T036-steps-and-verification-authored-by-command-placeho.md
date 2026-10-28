# T036 Passi e verifica compilati da comando; segnaposto rifiutati

- id: T036
- title: Passi e verifica compilati da comando; segnaposto rifiutati
- category: engine
- priority: P1
- priority-reason: Modifica prioritaria per due sessioni; ~40 riscritture manuali; i task con segnaposto passano validate
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N013, N017
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/tasks/T036-steps-and-verification-authored-by-command-placeho.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- use-cases: UC004
- short: Passi da comando

## Goal

'tasks new' accetta gli argomenti ripetibili --step e --verification; 'tasks step add|check|uncheck <id> "<text>"' modifica la checklist con la consueta anteprima/hash; validate segnala errore (o avviso, secondo quanto stabilito dalla specifica) sulle righe segnaposto 'Implement task steps.' / 'Verify task implementation.'.

## Steps

- [x] Aggiungere gli argomenti ripetibili --step e --verification a tasks new
- [x] Applicare il rifiuto/gli avvisi sui segnaposto in tasks validate
- [x] Aggiungere i sottocomandi tasks step list, add, check e uncheck e registrarli in is_mutating_command
- [x] Aggiungere unit test in test_tasks_engine.py e verificare che tutti i test passino

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k "step or placeholder or new"` passa.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
