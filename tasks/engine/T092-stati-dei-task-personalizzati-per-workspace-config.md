# T092 Stati dei task personalizzati per workspace (configurazione di progetto)

- id: T092
- title: Stati dei task personalizzati per workspace (configurazione di progetto)
- category: engine
- priority: P2
- priority-reason: Evita rilasci del motore per ogni ciclo di vita di progetto; nessuna urgenza dopo tracked (T091)
- next-up: no
- state: open
- executor: -
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261119-170945-custom-task-states-per-workspace-project/note.md
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Read tasks/engine/T092-stati-dei-task-personalizzati-per-workspace-config.md, do the open steps, run the Verification, update the task and the registry.
- kind: feature
- short: Stati per workspace

## Goal

Permettere a un progetto di dichiarare stati aggiuntivi senza modificare tasks_engine.py: nome, maps-to (stato canonico usato per derivazione e conteggio), terminale sì/no, transizioni ammesse in entrata e in uscita, etichetta e sezione opzionali nel registro. Gli stati sconosciuti continuano a fallire la validazione; uno stato personalizzato non può ridefinire uno canonico.

## Steps

- [ ] Scegliere dove si dichiarano (blocco TOML Project settings in tasks/AGENTS.md o tasks/states.toml) e lo schema
- [ ] normalize_state, is_valid_state, transizioni, derivazione, validate, sync-index e UI leggono l'insieme unito (canonici + progetto)
- [ ] Documentare in SKILL.md (States) e nel template

## Verification

- Test: stato di progetto accettato, stato sconosciuto rifiutato, ridefinizione di uno canonico rifiutata, derivazione tramite maps-to
- Suite di test del progetto verde

## Log (newest first)

- 2026-11-19, claude: nota dall'implementazione di T091 (Stato tracked). `tracked` è stato aggiunto come stato canonico nel codice, senza punto di estensione. I punti che uno stato di progetto deve toccare sono gli stessi: `CANONICAL_STATES`, `ALLOWED_TRANSITIONS`, la lista base di `normalize_state`, `derive_container_state` (`tracked` deriva come `waiting`: è il caso concreto di `maps-to`), `UC_STAGE_NOT_STARTED_STATES`, `valid_start` e i passi di `tasks close`, la riga di conteggio del registro (`_tracked_summary_line`), `ALLOWED_MODES_PER_STATE` in `scripts/orchestration_runs.py` e gli stati dell'UI.
