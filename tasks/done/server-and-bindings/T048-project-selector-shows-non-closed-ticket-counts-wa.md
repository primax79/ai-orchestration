# T048 Il selettore di progetto mostra il conteggio dei ticket non chiusi (waiting, open, progress)

- id: T048
- title: Il selettore di progetto mostra il conteggio dei ticket non chiusi (waiting, open, progress)
- category: server-and-bindings
- priority: P1
- priority-reason: Con oltre 400 progetti in workspace multi-progetto come porting_liferay, gli utenti hanno bisogno dei conteggi dei ticket non chiusi (waiting, open, progress) accanto al nome di ciascun progetto nel menu a tendina
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: ../ai-orchestration-ui/frontend/src/components/Navbar.tsx, ../vscode-ai-orchestration/src/extension.ts
- handoff: Leggere tasks/server-and-bindings/T048-project-selector-shows-non-closed-ticket-counts-wa.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- use-cases: UC033
- short: Conteggi attivi selettore progetti

## Goal

Mostrare il totale dei ticket non chiusi e la relativa ripartizione (waiting, open, progress) accanto al nome di ciascun progetto nel menu a tendina del selettore di progetto (e nell'opzione All projects), ordinando i progetti attivi in cima subito dopo _workspace.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
