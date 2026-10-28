# T055 I report delle campagne non diventano mai categorie; sync-index rimuove le categorie scomparse

- id: T055
- title: I report delle campagne non diventano mai categorie; sync-index rimuove le categorie scomparse
- category: engine
- priority: P2
- priority-reason: Una cartella di report generata compare come categoria di task e sopravvive alla propria cancellazione
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N055 (ai-coding-tools-2c)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T055-campaign-reports-never-become-categories-sync-inde.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: ai-coding-tools-2c
- verify-by: ai-coding-tools
- short: Nessuna categoria fantasma

## Goal

La campagna di validazione scrive il proprio report fuori dallo spazio dei nomi delle categorie (ad es. tasks/_reviews/ o una cartella riservata tasks/reports/ aggiunta a RESERVED_DIRS), così sync-index non la elenca mai come categoria; sync-index ricostruisce l'elenco delle categorie a partire dalle cartelle che contengono effettivamente dei task, così una categoria eliminata scompare da 00-INDEX.md; i test coprono entrambi i casi.

## Steps

- [x] Configurare `run_validation_campaign` per scrivere i report in `tasks/_reviews/` e aggiungere `"reports"` a `RESERVED_DIRS`.
- [x] Aggiornare `render_synced_index` e `merge_index_three_way` in `tasks_engine.py` per costruire l'elenco "Tasks by category" solo dalle cartelle di categoria che esistono e contengono almeno un task attivo.
- [x] Aggiungere 4 unit test in `test_tasks_engine.py` per verificare che i report delle campagne vadano in `_reviews/`, che `tasks/reports/` non sia una categoria, che le tabelle delle categorie svuotate o eliminate vengano rimosse da sync-index e che sync-index sia idempotente.
- [x] Eseguire l'intera suite pytest su `plugins/architect-side/skills/task-pipeline/scripts/` (227 passati).
- [x] Verificare che l'anteprima di `sync-index` su questo repository rimuova le categorie vuote e mantenga `engine` con i task attivi.

## Verification

- [x] `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/ -k "test_t055"` (4 passati in 3.57s)
- [x] `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` (227 passati in 154.34s)
- [x] `~/.pyenv/shims/python3 plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py sync-index --tasks-dir tasks` (l'anteprima conferma la rimozione delle tabelle delle categorie vuote e il mantenimento della categoria attiva `engine`)

## Log (newest first)

- 2026-10-25, ai-coding-tools-2c: state `verified` -> `done` — validazione del richiedente su una copia temporanea di tasks/ del workspace ai-coding-tools: un file inserito in tasks/reports/ non crea alcuna categoria; sync-index --apply ha mantenuto tutte le 36 righe di task (stessi id dell'indice reale), restano solo le sezioni tooling/investigations (skills rimossa: tutti done), secondo sync 'already in sync', validate pulito
- 2026-10-25, ai-coding-tools-2c: state `delivered` -> `verified` — validazione del richiedente su una copia temporanea di tasks/ del workspace ai-coding-tools: un file inserito in tasks/reports/ non crea alcuna categoria; sync-index --apply ha mantenuto tutte le 36 righe di task (stessi id dell'indice reale), restano solo le sezioni tooling/investigations (skills rimossa: tutti done), secondo sync 'already in sync', validate pulito
- 2026-10-25, kilo: state `open` -> `delivered` — Report delle campagne scritti in _reviews, reports aggiunto a RESERVED_DIRS, sync-index rimuove le categorie vuote; 227 test passati
