# T085 adopt-links espande i collegamenti a iniziative nei loro task

- id: T085
- title: adopt-links espande i collegamenti a iniziative nei loro task
- category: engine
- priority: P1
- priority-reason: Blocca 17.13: i 34 use case di ai-swissknife puntano a iniziative intere (62 collegamenti rifiutati)
- next-up: no
- state: in progress
- executor: kilo
- depends-on: 17.4
- decider: -
- sources: 17.13 (prova su ai-swissknife 2026-10-28)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T085-adopt-links-espande-i-collegamenti-a-iniziative-ne.md, do the open steps, run the Verification, update the task and the registry.
- short: Espansione iniziative

## Goal

use-cases adopt-links --expand-initiatives: un id di iniziativa nel linked-tasks di uno use case diventa il collegamento a tutti i task foglia non abbandonati dell'iniziativa (anche in done/), con anteprima che mostra l'espansione; senza l'opzione il comportamento resta fail-closed. Decisione dell'orchestratore (minore): espansione esplicita, nessun collegamento a livello di iniziativa.

## Steps

- [ ] Opzione --expand-initiatives in adopt-links, espansione nei task foglia non dropped, report dell'espansione
- [ ] Test su albero con iniziative attive e in done/
- [ ] Messaggio di rifiuto di `use-cases validate` per gli use case in draft/planned: oltre a `--force`, suggerire di approvare lo use case e collegare i task (suggerimento di ai-coding-tools-58)
- [ ] Prova su copia dell'albero di ai-swissknife: 62 collegamenti espansi, zero rifiuti

## Verification

- Anteprima su copia di ai-swissknife: nessun riferimento non canonico; stadi derivati coerenti

## Log (newest first)

- 2026-10-28, orchestrator: state `open` -> `in progress` — kilo 7e7002a32e79
