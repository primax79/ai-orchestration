# T039 Adozione di alberi esistenti: cartella legacy plans/, anteprima di next-id, discover prima della registrazione

- id: T039
- title: Adozione di alberi esistenti: cartella legacy plans/, anteprima di next-id, discover prima della registrazione
- category: engine
- priority: P2
- priority-reason: I nuovi alberi nascono accanto a layout legacy; gli id annunciati prima della creazione entrano in collisione
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N001, N014, N015
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, scripts/orchestration_registry.py
- handoff: Leggi tasks/tasks/T039-adopting-existing-trees-legacy-plans-next-id-previ.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- use-cases: UC030
- short: Supporto adozione alberi

## Goal

'tasks upgrade --dry-run' (o un comando normalize) propone di spostare un macropiano legacy plans/NN-*/ dentro tasks/; 'tasks new --dry-run' stampa l'id che verrebbe assegnato; 'projects discover <path>' funziona in sola lettura su un workspace non registrato. Inoltre (inbox N038): validate emette un avviso, senza mai fallire, sui campi header a testo libero legacy dei vecchi task. Inoltre (inbox N043): il registro avvisa dei progetti registrati la cui cartella non esiste più, e 'projects discover' stampa i progetti aggiunti/rimossi anziché l'intero elenco.

## Steps
- [x] Implementato secondo la specifica e l'obiettivo del task.
## Verification
- [x] Verificato tramite la suite di test automatizzati e i controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Eseguito merge di aeaced7; verificati tasks next-id, rilevamento di plans/ legacy in upgrade e projects discover prima della registrazione
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Assegnazione di T039 (Adozione di alberi esistenti: cartella legacy plans/, anteprima di next-id, discover prima della registrazione) a Kilo
