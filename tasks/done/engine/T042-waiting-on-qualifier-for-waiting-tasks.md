# T042 Qualificatore waiting-on per i task in attesa

- id: T042
- title: Qualificatore waiting-on per i task in attesa
- category: engine
- priority: P2
- priority-reason: I coordinatori non riescono a distinguere nell'indice i task in attesa dell'owner da quelli in attesa di terze parti
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N036 (gcube_audit, N035 consultation)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T042-waiting-on-qualifier-for-waiting-tasks.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- short: Qualificatore waiting-on

## Goal

Un task nello stato 'waiting' può avere un header 'waiting-on' (owner, team, external, o un breve testo libero), impostato dalla transizione o da un comando set, mostrato nell'indice e nelle UI e filtrabile; non è un nuovo stato.

## Steps
- [x] Implementato secondo la specifica e l'obiettivo del task.
## Verification
- [x] Verificato tramite la suite di test automatizzati e i controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Eseguito merge di 512a93c; verificato il qualificatore waiting-on tra CLI, 00-INDEX.md e validazione (173 passati)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Assegnazione di T042 (Qualificatore waiting-on per i task in attesa) a Kilo
