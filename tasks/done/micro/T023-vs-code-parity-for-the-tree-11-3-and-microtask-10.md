# T023 Parità VS Code per i messaggi Tree (11.3) e microtask (10.5)

- id: T023
- title: Parità VS Code per i messaggi Tree (11.3) e microtask (10.5)
- category: micro
- priority: P2
- priority-reason: La webview invia nuovi tipi di messaggio privi di handler; il rilascio dell'estensione dipende da questo
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: ../vscode-ai-orchestration/src/views/dashboard-panel.ts
- handoff: Leggere tasks/micro/T023-vs-code-parity-for-the-tree-11-3-and-microtask-10.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Parità albero VS Code

## Goal

Aggiungere gli handler dell'estensione per ogni tipo di messaggio ora inviato dalla dashboard (azioni sulla struttura dell'albero, creazione microtask, promozione, impostazione kind, impostazione etichette, elenco etichette) affinché test-bridge-parity sia verde, quindi sincronizzare la webview e rilasciare l'estensione.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
