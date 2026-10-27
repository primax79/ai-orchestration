# T030 Header conditions: per i task completati con domande aperte che possono modificare il risultato

- id: T030
- title: Header conditions: per i task completati con domande aperte che possono modificare il risultato
- category: server-and-bindings
- priority: P2
- priority-reason: Inoltrato dalla sessione centrale di Evolution Assurance (suo T023, decisione dell'owner Q005, metodo docs/08 §7.15)
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/server-and-bindings/T030-conditions-header-for-tasks-done-with-open-questio.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Completamento condizionato

## Goal

Un header conditions: (ID di domande aperte la cui risposta può modificare un risultato già concluso; distinto da blocks:): validate controlla che ogni ID esista; sync-index genera una sezione 'Conditional' sopra Done elencando tali task come 'done, conditional (Qnnn)'; quando tutte le condizioni hanno ricevuto risposta l'indicatore scompare; una risposta che modifica il risultato apre un task di follow-up. UI (ai-orchestration-ui, VS Code): badge distinto e contatore KPI.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
