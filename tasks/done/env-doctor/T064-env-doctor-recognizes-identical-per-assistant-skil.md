# T064 env doctor riconosce come intenzionali le copie identiche delle skill per assistente tra ~/.claude/skills e ~/.kilo/skills

- id: T064
- title: env doctor riconosce come intenzionali le copie identiche delle skill per assistente tra ~/.claude/skills e ~/.kilo/skills
- category: env-doctor
- priority: P2
- priority-reason: 6 falsi positivi di duplicazione sulle skill standalone accoppiate Claude/Kilo
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-170336-env-doctor-flags-per-assistant-skill-cop/note.md
- paths: -
- handoff: Leggere tasks/env-doctor/T064-env-doctor-recognizes-identical-per-assistant-skil.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Copie skill identiche nel Doctor

## Goal

Segnalazione dell'owner del 2026-10-25 (screenshot della UI del Doctor): ADVICE 'duplicate-name: orchestration-metrics / orchestration-setup / pdf / task-pipeline / task-spec-authoring ...: duplicate standalone skill across origins (standalone:~/.claude/skills, standalone:~/.kilo/skills): review and remove one manually'. Owner: questi non sono duplicati.

## Steps

- [x] Saltare `duplicate-name` in `orchestration_env.py` quando le voci standalone nello stesso scope hanno al massimo una copia per famiglia di root dell'assistente e contenuto equivalente.

## Verification

- [x] `pytest scripts/test_orchestration_env.py -k test_n063`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
