# T020 Test del motore di esecuzione instabili sotto carico

- id: T020
- title: Test del motore di esecuzione instabili sotto carico
- category: micro
- priority: P2
- priority-reason: Le esecuzioni rosse mascherano regressioni reali; osservato durante 07.12, 09.4 e il merge di 11.1
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/test_orchestration_runs.py, scripts/orchestration_runs.py
- handoff: Leggere tasks/micro/T020-flaky-run-engine-tests-under-load.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- short: Test run instabili

## Goal

test_preview_side_effect_free (mancata corrispondenza dell'hash) e test_reconcile_pid_reuse_simulated_does_not_kill (processo non attivo) falliscono circa una volta ogni due esecuzioni complete di scripts/test_orchestration_runs.py, mai in isolamento. Individuare la causa radice (stato condiviso, tempistiche, PID reali) e renderli deterministici senza indebolire i controlli effettuati.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
