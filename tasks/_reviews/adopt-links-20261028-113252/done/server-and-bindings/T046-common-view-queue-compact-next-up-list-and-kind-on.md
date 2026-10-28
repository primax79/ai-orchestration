# T046 Coda della vista comune: elenco next-up compatto e tipo di task sulle righe

- id: T046
- title: Coda della vista comune: elenco next-up compatto e tipo di task sulle righe
- category: server-and-bindings
- priority: P3
- priority-reason: Usabilità: 41 schede nella coda All-projects
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N044 (d4science-python-library validation of 16.9)
- paths: ../ai-orchestration-ui/frontend/src
- handoff: Leggere tasks/server-and-bindings/T046-common-view-queue-compact-next-up-list-and-kind-on.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Coda comune compatta

## Goal

Nella vista All-projects la scheda Queue mostra un elenco next-up compatto (come nella vista di progetto, pochi elementi per progetto o complessivi) con un link all'elenco completo, e le righe del backlog mostrano il kind del task.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
