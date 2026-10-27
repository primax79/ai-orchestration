# T029 Gli ID dei task di piano con suffisso alfabetico scompaiono dall'indice

- id: T029
- title: Gli ID dei task di piano con suffisso alfabetico scompaiono dall'indice
- category: server-and-bindings
- priority: P2
- priority-reason: Inoltrato dalla sessione centrale di Evolution Assurance (suo T021): i task ### 06.1b spariscono silenziosamente dall'indice e dal conteggio dell'iniziativa
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/server-and-bindings/T029-plan-task-ids-with-a-letter-suffix-drop-out-of-the.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: ID piano con suffisso lettera

## Goal

tasks_engine.py non effettua il parsing dei task di piano con suffisso alfabetico (### 06.1b - ...); validate emette solo un avviso sulla mancanza del separatore ' - ' mentre il task scompare dall'indice e dal conteggio dell'iniziativa. Accettare gli ID NN.Tx ovunque vengano analizzati gli ID (blocchi di piano, depends-on, transizioni, riferimenti qualificati) oppure rifiutarli con un ERROR di validate che ne indichi la causa; non scartare mai un blocco silenziosamente.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
