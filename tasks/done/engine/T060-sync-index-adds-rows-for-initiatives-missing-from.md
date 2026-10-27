# T060 sync-index aggiunge le righe per le iniziative mancanti dall'indice

- id: T060
- title: sync-index aggiunge le righe per le iniziative mancanti dall'indice
- category: engine
- priority: P2
- priority-reason: Iniziative silenziosamente assenti dal registro; dave_agent ha dovuto aggiungere sei righe a mano
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-130216-sync-index-never-adds-rows-for-new-initi/note.md; _inbox/analyzed/20261025-160659-sync-index-inserts-a-duplicate-specs-hea/note.md
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py
- handoff: Leggi tasks/engine/T060-sync-index-adds-rows-for-initiatives-missing-from.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- verify-by: dave_agent
- short: Aggiunta righe iniziative

## Goal

In dave_agent (2026-10-25) le iniziative 40-45 esistevano come NN-slug/plan.md, venivano analizzate da 'tasks list' e conteggiate da 'tasks validate' (46 iniziative), ma 'tasks sync-index --apply' non le aggiungeva mai alla tabella generata delle iniziative in 00-INDEX.md: aggiornava solo lo stato delle righe già presenti (17, 20). Dopo aver aggiunto le sei righe a mano dentro il blocco ai-orch:generated, una nuova sincronizzazione le ha mantenute compilando lo stato derivato (es. 'in progress (done: 40.1-40.2, 40.11; next: 40.3-40.10)'). Comportamento atteso: sync-index genera una riga per ogni iniziativa analizzata, aggiungendo quelle mancanti. Inoltre: senza --apply il comando mostra solo un'anteprima, cosa facile da non notare (un output nello stile di '[ok]' aiuterebbe a indicare 'preview only, not written').

## Steps

- [x] Aggiungere le iniziative attive mancanti in `render_synced_index`, correggere l'intestazione duplicata `## Specs` priva di marcatori (`N062`) e stampare l'avviso di anteprima quando `--apply` è omesso.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t060`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `open` -> `delivered` — `render_synced_index` aggiunge le righe delle iniziative mancanti in ordine numerico con stato derivato preservando le righe e il formato esistenti; l'anteprima di `sync-index` termina con `[preview] nothing written; re-run with --apply to write these changes`.
