# T018 Follow-up di Q003: precedenza quando coesistono orchestration-workflow e la skill di orchestrazione generica

- id: T018
- title: Follow-up di Q003: precedenza quando coesistono orchestration-workflow e la skill di orchestrazione generica
- category: env-doctor
- priority: P2
- priority-reason: Risposta aperta dell'owner a Q003: chiarire se sono incompatibili o solo formulate come tali; serve una regola di priorità o indicazioni a livello di prompt
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: claude
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/env-doctor/T018-q003-follow-up-precedence-when-orchestration-workf.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Precedenza skill orchestrazione

## Goal

Confrontare le due skill, stabilire se sono effettivamente in conflitto o se si sovrappongono solo nella formulazione e proporre una regola di precedenza (quale prevale quando vengono caricate entrambe) scritta in ambedue le skill, così che il Doctor possa trattare la coppia come riconosciuta. Contesto decisionale: questions/Q003.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
