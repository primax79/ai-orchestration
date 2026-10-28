# T027 Il recupero dei claim scaduti riavvia un turno il cui processo figlio non ha ancora scritto il proprio pid

- id: T027
- title: Il recupero dei claim scaduti riavvia un turno il cui processo figlio non ha ancora scritto il proprio pid
- category: server-and-bindings
- priority: P1
- priority-reason: Revisione di Gemini del 2026-10-18: viola il principio 'mai due riprese della stessa sessione contemporaneamente'
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/server-and-bindings/T027-stale-claim-recovery-relaunches-a-turn-whose-child.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- use-cases: UC028
- short: Ripresa duplicata del turno

## Goal

run_next_turn acquisisce il claim di un turno, rilascia il lock dell'orchestratore e il pid viene scritto solo dopo l'avvio del processo figlio; un run-next concorrente vede pid=None e tratta il claim come terminato in modo anomalo (orchestration_orchestrator.py:1034-1052, :1112, :1186-1193), rimettendolo in coda e avviando una seconda ripresa della sessione. Rispettare lease_expires_at e un periodo di tolleranza all'avvio prima di recuperare un claim privo di pid; aggiungere un test che esegua due svuotamenti concorrenti della coda su uno stub ad avvio lento e verifichi che avvenga una sola ripresa.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
