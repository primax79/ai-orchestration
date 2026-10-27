# T058 Collisioni di id tra branch e merge driver pendente

- id: T058
- title: Collisioni di id tra branch e merge driver pendente
- category: engine
- priority: P2
- priority-reason: Due branch che eseguono entrambi 'tasks new' ottengono lo stesso T###; dopo il merge validate fallisce e l'indice mantiene una sola riga
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N032 (folded into T037, not solved there); T037 live check 2026-10-25
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T058-id-collisions-across-branches-and-a-dangling-merge.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- short: Collisioni id tra branch

## Goal

Dopo un merge in cui due branch hanno allocato lo stesso id di task, 'ai-orch tasks renumber --dry-run' (o il suggerimento di correzione di validate) propone il successivo id libero per il file più recente, ne riscrive l'header, il nome del file e i link, e l'indice recupera entrambe le righe; validate inoltre avvisa quando il comando merge.ai-orch-index.driver configurato non esiste più (ad es. il percorso di un worktree rimosso).

## Steps

- [x] Scansionare i branch git locali e i worktree fratelli in `_scan_git_branch_and_worktree_ids` per `T###`, `Q###`, `UC###`, `N###` e controllare i duplicati `N###` in `validate_tasks_tree`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
