# T053 Rendere deterministico test_confirm_start_run_hash_mismatch_if_plan_changed

- id: T053
- title: Rendere deterministico test_confirm_start_run_hash_mismatch_if_plan_changed
- category: engine
- priority: P2
- priority-reason: Un test instabile nasconde i fallimenti reali e blocca i merge protetti da gate
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N054
- paths: conftest.py, scripts/orchestration_runs.py, scripts/orchestration_env.py, scripts/test_orchestration_triggers.py, scripts/test_orchestration_runs.py, scripts/test_orchestration_env.py, scripts/test_orchestration_invoke.py, scripts/test_orchestration_orchestrator.py, plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py
- handoff: Leggi tasks/engine/T053-make-test-confirm-start-run-hash-mismatch-if-plan.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: ai-coding-tools-c1
- short: Test trigger instabile

## Goal

Il test passa in modo deterministico sotto carico: individuare l'assunzione temporale dietro 'preview_failed' (osservato una volta in un'esecuzione della suite da 32 minuti, mentre passa se eseguito da solo), correggere il test o il codice, e dimostrarlo con 20 esecuzioni consecutive sotto stress della CPU (ad es. eseguendolo in parallelo con altri test). Lo stesso vale per scripts/test_orchestration_runs.py::test_t022_cancel_stops_tool_children_in_new_session (fallito una volta in un'esecuzione completa da 13 minuti il 2026-10-25, passa da solo 6/6 su main e su un branch): probabilmente un'assunzione temporale sulla terminazione dei processi. Causa radice individuata per i test dei trigger (2026-10-25): invocano la vera CLI `kilo` per un controllo di versione con timeout di 5 s ('Run preview failed: Version check timed out (5s) for kilo'), che scade quando molte esecuzioni di Kilo caricano la macchina; test_confirm_start_run_starts_stub_run è fallito allo stesso modo. I test devono sostituire con uno stub il controllo di versione della CLI (nessun sottoprocesso `kilo` reale negli unit test).

## Steps

- [x] Sostituire con stub i controlli di versione della CLI in `conftest.py` (`AI_ORCH_TEST_CLI_VERSIONS`) e rispettare l'override in `scripts/orchestration_runs.py` (`_default_cli_version_probe` / `check_tool_availability`) e `scripts/orchestration_env.py` (`check_cli_binary`), oltre ad aggiungere fixture autouse con CLI fittizie in `scripts/test_orchestration_triggers.py`, `scripts/test_orchestration_env.py` e `plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py` affinché nessun unit test avvii i binari reali `kilo`/`claude`/`codex` (con test di opt-out esplicito `test_tool_availability_default_version_probe_with_fake_binary`).
- [x] Sostituire le attese fisse di 5 s in `scripts/test_orchestration_runs.py::test_t022_cancel_stops_tool_children_in_new_session` (e nei test fratelli di cancel/invoke/trigger/orchestrator) con un polling fino a 30 s che attende sia il file PID del processo nipote sia il record `agent` del supervisore (`pid`, `pgid`, `start_time`) prima di invocare `run cancel`, e attende in polling fino a 30 s la terminazione del processo.
- [x] Eseguire ciascuno dei tre test 20 volte di seguito sotto stress CPU a 8 worker, verificare con CLI avvelenate (`exit 99`) messe per prime in `PATH`, ed eseguire l'intera suite di test.

## Verification

- 20 esecuzioni consecutive sotto stress a 8 CPU (`python3 -c "while True: pass"` x 8):
  - `scripts/test_orchestration_triggers.py::test_confirm_start_run_hash_mismatch_if_plan_changed`: `20/20 passed`
  - `scripts/test_orchestration_triggers.py::test_confirm_start_run_starts_stub_run`: `20/20 passed`
  - `scripts/test_orchestration_runs.py::test_t022_cancel_stops_tool_children_in_new_session`: `20/20 passed`
- Controllo con CLI avvelenate (falsi `kilo`, `claude`, `codex` che escono con 99 messi per primi in `PATH`):
  - `PATH="/tmp/poison-bin:$PATH" ~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/test_orchestration_triggers.py scripts/test_orchestration_env.py plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py` -> `27 passed`, `81 passed`, `37 passed`.
- Intera suite di test:
  - `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/` -> `579 passed in 337.82s`.

## Log

- 2026-10-25, ai-coding-tools-c1: state `verified` -> `done`
- 2026-10-25, ai-coding-tools-c1: state `delivered` -> `verified`
- 2026-10-25, kilo: state `open` -> `delivered` — sostituiti con stub i probe di versione della CLI e sostituite le attese fisse di avvio/cancellazione con polling condizionale a 30s; 20/20 esecuzioni sotto stress e intera suite (579 test) verdi.
