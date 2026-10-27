# T062 La transizione a delivered rifiuta le sezioni con segnaposto del template

- id: T062
- title: La transizione a delivered rifiuta le sezioni con segnaposto del template
- category: engine
- priority: P2
- priority-reason: I task raggiungono lo stato delivered con Steps/Verification vuoti; solo validate lo intercetta in seguito
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-145247-transition-to-delivered-accepts-template/note.md
- paths: -
- handoff: Leggi tasks/engine/T062-transition-to-delivered-refuses-template-placehold.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- verify-by: ai-coding-tools
- short: No consegna con segnaposto

## Goal

Il 2026-10-25 i task T032-T034 (workspace ai-coding-tools) sono passati a delivered con '- [ ] Step 1' e '- Command or check that proves completion' ancora presenti; solo un successivo 'tasks validate' lo ha segnalato (rilevato da ai-coding-tools-2c). Comportamento atteso: 'transition <id> delivered' (e l'avanzamento automatico fino a done) rifiuta l'operazione finché una delle due sezioni contiene ancora il segnaposto del template, indicando la sezione, proprio come fa validate.

## Steps

- [x] Rifiutare `transition <id> delivered` quando `## Steps` o `## Verification` contiene ancora righe segnaposto del template.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
