# T022 Correzioni al motore di esecuzione emerse dalla cattura live 07.5/12.1

- id: T022
- title: Correzioni al motore di esecuzione emerse dalla cattura live 07.5/12.1
- category: server-and-bindings
- priority: P1
- priority-reason: Una run può eliminare il worktree di un'altra run; altri bug lasciano i task bloccati o li eseguono in directory vuote
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/orchestration_runs.py, scripts/test_orchestration_runs.py
- handoff: Leggere tasks/server-and-bindings/T022-run-engine-fixes-found-by-the-07-5-12-1-live-captu.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Fix motore di esecuzione

## Goal

Correggere i problemi del motore elencati in tasks/12-events-and-triggers/notes/12.1-resumption-facts.md: (1) l'annullamento di una run deve fermare anche i processi figli dei tool di Kilo; (2) la ripresa di una run di verifica o di una run il cui worktree è stato rimosso deve essere rifiutata, non eseguita in una directory vuota; (3) una run di verifica deve rimuovere solo i worktree che ha creato; (4) la transizione a in-progress del supervisore non deve lasciare sporco il repository di destinazione (seconda esecuzione rifiutata); (5) una run di esecuzione fallita deve permettere al task di tornare a open/bounced con una motivazione; (6) documentare/gestire il fatto che una sessione di Kilo si riprende solo dal proprio repository originale; (7) una run di verifica senza --profile deve usare il profilo/routing configurato, senza mai ripiegare silenziosamente su modelli predefiniti costosi (e Kilo deve restare su gemini-3.8-flash).

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
