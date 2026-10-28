# T041 Domande: risposte non applicate messe in evidenza, stato moved-to-tracker, sezione Notes

- id: T041
- title: Domande: risposte non applicate messe in evidenza, stato moved-to-tracker, sezione Notes
- category: engine
- priority: P1
- priority-reason: Le domande con risposta sono rimaste non applicate per due giorni senza essere notate (modifica prioritaria per evolution-assurance)
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: ai-orchestration inbox N009, N016, N019, N020
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/tasks/T041-questions-unapplied-answers-surfaced-moved-to-trac.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- use-cases: UC027
- short: Lacune flusso domande

## Goal

validate e sync-index avvisano delle domande con risposta ma non ancora applicate e l'indice le mostra; 'questions answer' può applicare la risposta nella stessa chiamata (--apply-ref, --note); uno stato 'moved' con collegamento esterno per le domande trasformate in ticket sul tracker; una sezione libera opzionale 'Notes' nei file delle domande; la documentazione presenta '--blocks -' come il modo per porre una domanda non bloccante.

## Steps
- [x] Implementato secondo la specifica e l'obiettivo del task.
## Verification
- [x] Verificato tramite la suite di test automatizzati e i controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Eseguito merge di 29f852c; verificati l'evidenziazione delle risposte non applicate, questions move, --blocks - non bloccante e ## Notes (163 passati)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Assegnazione di T041 (Ciclo di vita delle domande: risposte non applicate, move-to-tracker, non bloccanti, sezione Notes) a Kilo

## Validazione del richiedente (2026-10-25)

OK da gcube-audit: `questions move ... --to <url>` imposta lo stato moved e compare in `questions list`; `questions list` stampa l'avviso delle risposte non applicate e `validate` emette un avviso per ogni domanda. Lacuna minore registrata come T052.
