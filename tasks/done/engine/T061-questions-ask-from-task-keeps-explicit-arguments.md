# T061 questions ask --from-task mantiene gli argomenti espliciti

- id: T061
- title: questions ask --from-task mantiene gli argomenti espliciti
- category: engine
- priority: P2
- priority-reason: Domande per l'owner create con opzioni vuote e richiedente errato; le sessioni devono riscriverle a mano
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-145357-questions-ask-from-task-ignores-question/note.md
- paths: -
- handoff: Leggi tasks/engine/T061-questions-ask-from-task-keeps-explicit-arguments.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- verify-by: ai-coding-tools
- short: Ask from-task mantiene argomenti

## Goal

Riproduzione (2026-10-25, workspace ai-coding-tools): `ai-orch tasks questions ask --tasks-dir tasks --from-task T009 --decider owner --asked-by ai-coding-tools --question '...?' --context '...' --option 'A=...' --option 'B=...' --recommended A --blocks T009`. Risultato Q001: domanda e titolo copiati dal testo legacy di decider, contesto 'Converted from the legacy decider header ...; context to be completed by the owner', Options vuoto, recommended '-', asked-by 'owner', open-answer yes. Comportamento atteso: gli argomenti espliciti prevalgono sui valori derivati dal task; derivare solo ciò che manca. Ho riscritto Q001 e Q002 a mano.

## Steps

- [x] Preservare gli argomenti CLI espliciti (`--question`, `--context`, `--option`, `--recommended`, `--asked-by`, `--decider`, `--blocks`) quando `--from-task` viene passato a `questions ask`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
