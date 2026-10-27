# T051 tasks reopen va in crash sui task emergenti (TypeError in _update_index_task_path)

- id: T051
- title: tasks reopen va in crash sui task emergenti (TypeError in _update_index_task_path)
- category: engine
- priority: P1
- priority-reason: La riapertura è il percorso per ogni validazione NOT OK; va in crash a metà operazione
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: ai-coding-tools, 2026-10-25, reopening T035/T037
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T051-tasks-reopen-crashes-on-emergent-tasks-typeerror-i.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: ai-coding-tools-c1
- short: Crash su reopen

## Goal

'ai-orch tasks reopen T### --reason R --expect-plan-hash H' su un task emergente in done/ lo riporta indietro, lo imposta a open, aggiorna 00-INDEX.md e termina con codice 0. Oggi sposta il file e imposta lo stato, poi va in crash con 'TypeError: _update_index_task_path() got multiple values for argument old_rel', lasciando l'indice disallineato. Aggiungere un test di regressione per la riapertura di un task emergente (a file singolo e a cartella).

## Steps

- [x] Correggere la chiamata a _update_index_task_path in reopen (argomento old_rel duplicato) e gestire i task a cartella (git mv della cartella T###-slug)
- [x] Test di regressione per task emergenti a file singolo e a cartella e per il dry run (test_tasks_engine.py, 10 test di reopen passati)

## Verification

- Verifica dal vivo su una copia temporanea di ai-orchestration/tasks: `tasks reopen T034 --reason ... --expect-plan-hash ...` termina con codice 0, il file torna in server-and-bindings/, la riga dell'indice punta al nuovo percorso, `validate` e `sync-index --check` sono puliti (2026-10-25)
- Intera suite: 552 passati; l'unico fallimento (test_t022_cancel_stops_tool_children_in_new_session) passa da solo 6/6 ed è tracciato in T053

## Log (newest first)

- 2026-10-25, orchestrator: state `verified` -> `done` — Verificato dal richiedente
- 2026-10-25, ai-coding-tools-c1: state `delivered` -> `verified` — Verifica del richiedente (indipendente dall'executor, kilo): la riapertura dal vivo di T034 in stato done su una copia temporanea di ai-orchestration/tasks è terminata con codice 0, file tornato nella propria categoria, riga dell'indice aggiornata, validate e sync-index --check puliti (2026-10-25); 10 test di reopen passati
