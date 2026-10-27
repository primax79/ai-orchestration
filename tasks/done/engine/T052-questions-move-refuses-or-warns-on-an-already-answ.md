# T052 questions move rifiuta o avvisa su una domanda che ha già ricevuto risposta

- id: T052
- title: questions move rifiuta o avvisa su una domanda che ha già ricevuto risposta
- category: engine
- priority: P3
- priority-reason: Lacuna minore rilevata durante la validazione di T041
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N051 (gcube_audit)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T052-questions-move-refuses-or-warns-on-an-already-answ.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- short: Guardia move domanda risolta

## Goal

'ai-orch questions move Q###' su una domanda nello stato 'answered' rifiuta l'operazione con un messaggio che indica che la risposta dovrebbe essere applicata (questions apply), a meno che non venga specificato --force; coperto da un test.

## Steps

- [x] Aggiungere `force: bool = False` (`--force`) a `move_question` e `cmd_questions_move`, rifiutando le domande con `status: answered` senza `--force`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
