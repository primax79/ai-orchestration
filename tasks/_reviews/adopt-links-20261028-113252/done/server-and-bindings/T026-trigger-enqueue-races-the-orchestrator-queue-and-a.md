# T026 L'accodamento dei trigger entra in race condition con la coda dell'orchestratore e avanza troppo presto il cursore di ruolo

- id: T026
- title: L'accodamento dei trigger entra in race condition con la coda dell'orchestratore e avanza troppo presto il cursore di ruolo
- category: server-and-bindings
- priority: P1
- priority-reason: Rilevato dalla revisione di Codex del 2026-10-18: un trigger può sovrascrivere un turno in coda e alcuni eventi possono andare persi
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/server-and-bindings/T026-trigger-enqueue-races-the-orchestrator-queue-and-a.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Race accodamento trigger

## Goal

orchestration_triggers.py alloca <seq>.json per i turni event_batch senza il lock dell'orchestratore (dovrebbe chiamare la funzione canonica enqueue_turn) e avanza il cursore di ruolo condiviso nel momento stesso in cui accoda un turno, mentre la specifica events-and-triggers.md 0c stabilisce che il cursore avanza solo dopo il salvataggio persistente della trascrizione del turno. Fare in modo che i trigger accodino tramite enqueue_turn sotto lock, dotare la scansione dei trigger di un proprio cursore separato dal cursore di consegna del ruolo, avanzare il cursore di consegna solo dopo il completamento durevole del turno, aggiungendo test che riproducano la race condition (accodamento concorrente dell'owner + accodamento del trigger) e il caso di perdita di eventi (crash del turno dopo che il trigger ha avanzato il cursore). Evidenze dalla revisione: orchestration_triggers.py:938, :947, :1762; orchestration_orchestrator.py:627, :1372.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
