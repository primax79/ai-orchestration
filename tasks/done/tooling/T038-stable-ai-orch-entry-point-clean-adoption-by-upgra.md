# T038 Punto di ingresso ai-orch stabile; adozione pulita tramite upgrade

- id: T038
- title: Punto di ingresso ai-orch stabile; adozione pulita tramite upgrade
- category: tooling
- priority: P2
- priority-reason: Gli agenti passano al broker MCP (16.6); restano il fallback CLI e piccole correzioni
- next-up: no
- state: done
- executor: kilo
- depends-on: 16.6
- decider: -
- sources: feedback round 2026-10-21: inbox N003, N010, N011, N012
- paths: bin/ai-orch, scripts/orchestration_env.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggere tasks/tooling/T038-stable-ai-orch-entry-point-clean-adoption-by-upgra.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Punto di ingresso stabile

## Goal

Riperimetrato il 2026-10-21 (owner): gli agenti raggiungono il motore attraverso il broker MCP (16.6), che fornisce anche allo shim un percorso indipendente dalla versione; questo task mantiene solo il fallback CLI e piccole correzioni. Per le sessioni che lavorano senza MCP, 'ai-orch' viene eseguito dallo stesso percorso indipendente dalla versione (documentato nel README del plugin); l'esecuzione diretta dello script del motore non emette mai avvisi su orchestration_events; 'tasks upgrade' scrive tasks/.gitignore con il lock; il Doctor segnala come obsolete le copie vendored di tasks_engine.py interne ai progetti.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
