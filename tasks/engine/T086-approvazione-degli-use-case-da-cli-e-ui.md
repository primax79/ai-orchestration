# T086 Approvazione degli use case da CLI e UI

- id: T086
- title: Approvazione degli use case da CLI e UI
- category: engine
- priority: P1
- priority-reason: 71 use case (ai-orchestration, ai-swissknife) sono proposed dopo la migrazione e oggi si approvano solo editando i file
- next-up: no
- state: delivered
- executor: kilo
- depends-on: 17.11
- decider: -
- sources: 17.10 (verifica dal vivo della UI, 2026-10-28)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py; ../ai-orchestration-ui; ../vscode-ai-orchestration
- handoff: Read tasks/engine/T086-approvazione-degli-use-case-da-cli-e-ui.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: owner
- kind: feature
- short: Approvare use case

verification pending: run Verification checks (verify-by: owner)

## Goal

ai-orch tasks use-cases approve|deprecate|propose UC###[,UC###...] (anteprima, --apply --expect-plan-hash), con approved-by e data, evento use_case.approval_changed, modifica mirata dell'header; filtro --stage per approvare in blocco. API della UI e pulsanti: Approva su scheda e dettaglio, Approva selezionati, conferma con anteprima.

## Steps

- [x] Motore: comandi approve/deprecate/propose con anteprima e applicazione, filtri, evento, test
- [ ] Backend UI: endpoint preview/apply
- [ ] UI: pulsanti singoli e in blocco con conferma
- [ ] Estensione: handler del bridge
- [x] docs/use-case-migration.md passo 5 e SKILL.md: citare il nuovo comando di approvazione

## Verification

- Approvare in blocco i use case untested di una copia di ai-orchestration: anteprima corretta, apply, stage invariato, approval approved

## Log (newest first)

- 2026-10-28, orchestrator: state `in progress` -> `delivered` — Motore 0.8.17 (approve/deprecate/propose con anteprima e filtri), UI web (ai-orchestration-ui 5d8e2b6) in esecuzione su 8780, estensione 0.6.8 installata; anteprima dal vivo via API: 35 use case untested approvabili. Il proprietario valida approvando dalla UI
- 2026-10-28, orchestrator: state `open` -> `in progress` — kilo (parte motore)
