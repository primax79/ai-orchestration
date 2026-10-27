# T084 Test del backend della UI rossi su main

- id: T084
- title: Test del backend della UI rossi su main
- category: ui
- priority: P1
- priority-reason: 7 test falliscono su main di ai-orchestration-ui (2 in più sul branch di T075): blocca il merge di T075 e nasconde regressioni
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: verifica dell'architetto 2026-10-27 prima del merge di T075
- paths: ai-orchestration-ui/backend
- handoff: Read tasks/ui/T084-test-del-backend-della-ui-rossi-su-main.md, do the open steps, run the Verification, update the task and the registry.
- short: Test backend UI rossi

## Goal

La suite del backend di ai-orchestration-ui torna verde su main: per ciascun test che fallisce si trova la causa (cambi del motore di oggi: config show nella cartella corrente T072, reassign T070, validazione degli id; o test fragili) e si corregge il codice o il test con motivazione; nessun test disattivato senza motivo scritto.

## Steps

- [ ] Elenco dei 7 test con la causa di ciascuno
- [ ] Correzioni (codice o test) con motivazione

## Verification

- uv run --no-project --with-requirements backend/requirements-dev.txt python -m pytest -q backend/: 0 failed
