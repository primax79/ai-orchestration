# T045 Follow-up del broker dalla validazione: mcp --local, codici di errore stabili, campo project

- id: T045
- title: Follow-up del broker dalla validazione: mcp --local, codici di errore stabili, campo project
- category: server-and-bindings
- priority: P1
- priority-reason: 16.5 ha fallito la validazione sulla modalità in-process promessa; il contratto degli errori devia dalla specifica 3b
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N042, N045 (d4science-python-library validation of 16.5)
- paths: bin/ai-orch, ../ai-orchestration-ui/backend/broker/
- handoff: Leggere tasks/server-and-bindings/T045-broker-follow-ups-from-validation-mcp-local-stable.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- use-cases: UC032
- short: Follow-up validazione broker

## Goal

'ai-orch mcp --local' serve i tool del broker in-process (senza processo broker esterno) come promesso in 16.5; ogni errore del broker riporta un codice 'error' stabile in kebab-case (ad es. hash-mismatch) e un 'message' leggibile (nessun JSON grezzo della CLI); gli elementi di tasks.next e questions.list includono 'project', e il comando next a livello di workspace distingue gli elementi _workspace.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
