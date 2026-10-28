# T040 Task next-up e open a livello di intero workspace tra più progetti

- id: T040
- title: Task next-up e open a livello di intero workspace tra più progetti
- category: server-and-bindings
- priority: P2
- priority-reason: Comando più utilizzato per un workspace multi-repo; oggi richiede un grep per ciascun albero tasks
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N030
- paths: scripts/orchestration_registry.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggere tasks/server-and-bindings/T040-workspace-wide-next-up-and-open-tasks-across-proje.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- use-cases: UC033
- short: Next di workspace

## Goal

'ai-orch workspace next [--root P]' elenca i task next-up e open di ogni progetto del workspace (ID qualificati, titoli brevi, coordinate espanse), usando lo stesso risolutore della vista comune della UI.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Unito 4bc3793; verificati tasks next e list --workspace a livello di workspace (177 passati)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Invio di T040 (Task next-up e open a livello di workspace tra più progetti in una sola chiamata) a Kilo
