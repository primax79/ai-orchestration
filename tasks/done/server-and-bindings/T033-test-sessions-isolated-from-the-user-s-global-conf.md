# T033 Sessioni di test isolate dalla configurazione globale dell'utente

- id: T033
- title: Sessioni di test isolate dalla configurazione globale dell'utente
- category: server-and-bindings
- priority: P1
- priority-reason: Un test instabile del motore e cinque test delle run dipendevano dalla macchina dell'operatore (lock del broker attivo, mappatura dei modelli)
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: suite failures 2026-10-21
- paths: conftest.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggere tasks/server-and-bindings/T033-test-sessions-isolated-from-the-user-s-global-conf.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Isolamento config nei test

## Goal

Ogni sessione pytest riceve una configurazione globale temporanea con una mappatura fissa dei modelli, così che un broker avviato da un'altra sessione o la mappatura personale dell'operatore non possano alterare i risultati. Inoltre: l'anteprima di sync-index --adopt stampa l'hash necessario per applicarla. Consegnato in 4f1caab e 4a3c4f2; suite completa 490 passati.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
