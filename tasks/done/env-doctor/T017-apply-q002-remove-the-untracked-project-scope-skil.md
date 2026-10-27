# T017 Applicare Q002: rimuovere le copie non tracciate delle skill a livello di progetto in ai-orchestration

- id: T017
- title: Applicare Q002: rimuovere le copie non tracciate delle skill a livello di progetto in ai-orchestration
- category: env-doctor
- priority: P2
- priority-reason: L'owner ha risposto A a Q002; le copie obsolete oscurano le skill rilasciate in questo repository
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: claude
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/env-doctor/T017-apply-q002-remove-the-untracked-project-scope-skil.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Rimozione skill di progetto

## Goal

Eliminare le copie non tracciate delle skill sotto .claude/skills, .codex/skills e .kilo/skills del repository ai-orchestration (mai .kilo/worktrees né alcun file tracciato), dopo averle elencate; sono riproducibili dai plugin sorgente. Decisione: questions/Q002.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
