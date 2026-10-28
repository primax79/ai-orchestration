# T028 Turni non presidiati: applicare capacità ridotte su ogni tool e irrobustire i delimitatori dei dati non attendibili

- id: T028
- title: Turni non presidiati: applicare capacità ridotte su ogni tool e irrobustire i delimitatori dei dati non attendibili
- category: server-and-bindings
- priority: P1
- priority-reason: Revisione di Gemini del 2026-10-18: i turni evento di Kilo girano con tutti i tool abilitati; i dati non attendibili possono chiudere il proprio delimitatore
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/server-and-bindings/T028-unattended-turns-enforce-reduced-capability-on-eve.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Sicurezza turni non presidiati

## Goal

I turni a capacità ridotta (triage/event_batch) vengono limitati solo tramite la allow-list di Claude e la sandbox in sola lettura di Codex; l'adattatore di Kilo non passa alcuna restrizione (orchestration_runs.py:2098-2116), quindi i turni non presidiati di Kilo possono modificare ed eseguire qualsiasi cosa. Inoltre format_untrusted_event_data racchiude i dati in tag fissi che i dati stessi possono chiudere. Imporre un profilo ristretto per i turni non presidiati di Kilo (verificare le opzioni reali di permesso/agente di Kilo in references/ o con kilo --help prima di scegliere; rifiutare l'esecuzione di un turno Kilo non presidiato se non è disponibile alcuna restrizione) e racchiudere i dati non attendibili con un tag nonce casuale per turno più escaping, corredato da test.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
