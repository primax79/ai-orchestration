# T024 Confermare o rifiutare le azioni proposte dai trigger (motore + collegamento UI)

- id: T024
- title: Confermare o rifiutare le azioni proposte dai trigger (motore + collegamento UI)
- category: server-and-bindings
- priority: P2
- priority-reason: E3 trasforma le azioni mutanti non presidiate in proposte; oggi possono solo essere elencate
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/orchestration_triggers.py, ../ai-orchestration-ui/backend/server.py
- handoff: Leggere tasks/server-and-bindings/T024-confirm-or-reject-trigger-proposed-actions-engine.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Motore conferma proposte

## Goal

Aggiungere ai-orch triggers confirm ACTION_ID --expect-hash H e triggers reject ACTION_ID --reason R: confirm esegue il comando o la run proposta attraverso gli stessi percorsi di un'azione dell'owner (avvio della run con hash del piano per le run), registra l'esito ed emette gli eventi; reject registra la motivazione. Collegare quindi gli endpoint della UI (lasciati in sola lettura da 12.6) e gli handler di VS Code.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
