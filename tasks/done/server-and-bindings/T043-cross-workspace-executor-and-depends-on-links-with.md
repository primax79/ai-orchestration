# T043 Collegamenti executor e depends-on tra workspace diversi con stato in tempo reale

- id: T043
- title: Collegamenti executor e depends-on tra workspace diversi con stato in tempo reale
- category: server-and-bindings
- priority: P2
- priority-reason: Il lavoro svolto in un altro workspace viene tracciato a mano; le sessioni lo ritengono più utile degli stati personalizzati
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N039 (d4science-evolution-assurance, N035 consultation)
- paths: scripts/orchestration_registry.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggere tasks/server-and-bindings/T043-cross-workspace-executor-and-depends-on-links-with.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Link task cross-workspace

## Goal

'executor: <workspace>:T030' e i depends-on tra workspace diversi si risolvono tramite il registro dei workspace e mostrano lo stato in tempo reale del task remoto in validate, nell'indice e nelle UI, in sola lettura, come le coordinate interne a un workspace (16.4).

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Unito eddaeb5; verificati i collegamenti executor e depends-on cross-workspace con stato in tempo reale della destinazione (180 passati)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Invio di T043 (Collegamenti executor e depends-on cross-workspace con stato in tempo reale della destinazione) a Kilo
