# T044 Richieste di verifica persistenti indirizzate a un workspace o a una sessione

- id: T044
- title: Richieste di verifica persistenti indirizzate a un workspace o a una sessione
- category: engine
- priority: P1
- priority-reason: La validazione da parte dei richiedenti è la regola dell'owner, ma le richieste inviate come messaggi di sessione vanno perse quando una sessione si chiude (due su quattro perse il 2026-10-21)
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: owner 2026-10-21 (validation by requester; 'use something like questions'); method 0.17 (verification queue drained at session start); inbox N046 (gcube_atlas handover: Kilo/Gemini sessions cannot receive cross-session messages)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, skills
- handoff: Leggi tasks/engine/T044-durable-verification-requests-addressed-to-a-works.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- verify-by: gcube_atlas
- use-cases: UC037
- short: Richieste verifica persistenti

## Goal

Un task nello stato delivered può includere una richiesta 'verify-by: <workspace or session>' con ciò che va controllato, impostata tramite comando; 'ai-orch tasks verification-queue [--for <workspace>]' elenca le richieste indirizzate al workspace chiamante attraverso tutti i workspace registrati; l'indice e le UI le mostrano; le skill istruiscono ogni sessione a svuotare la propria coda all'avvio della sessione (metodo 0.17) e a rispondere con transition verified --verifier oppure con una nota NOT OK.

## Steps
- [x] Implementato secondo la specifica e l'obiettivo del task.
## Verification
- [x] Verificato tramite la suite di test automatizzati e i controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Eseguito merge di T044; verificati verify-by persistente e verification-queue tra i workspace
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Assegnazione di T044 (Richieste di verifica persistenti indirizzate a un workspace o a una sessione) a Kilo
