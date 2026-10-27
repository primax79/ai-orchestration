# T068 sync-index aggiorna le etichette delle iniziative quando cambia il titolo del piano

- id: T068
- title: sync-index aggiorna le etichette delle iniziative quando cambia il titolo del piano
- category: engine
- priority: P3
- priority-reason: Dopo la traduzione 65 etichette sono rimaste in inglese; sistemate a mano
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-122138-sync-index-keeps-stale-initiative-link-l/note.md
- paths: -
- handoff: Read tasks/engine/T068-sync-index-aggiorna-le-etichette-delle-iniziative.md, do the open steps, run the Verification, update the task and the registry.
- verifier: claude:ai-coding-tools
- verify-by: ai-coding-tools
- short: Etichette iniziative aggiornate

## Goal

After translating plan titles (T036, 2026-10-27) sync-index reported 'already in sync' in ai-orchestration (15 rows) and ai-swissknife (50 rows) while the Initiatives/Done link labels still showed the old English titles; I rewrote them with a script. The T050 rule that keeps a hand-curated label treats any label shorter than the title as curated. Expected: a label equal to a PREVIOUS title of the plan is not curated and follows the current title, or a 'sync-index --refresh-labels' option.

## Steps

- [x] Per le righe di iniziativa (link a `NN-slug/plan.md` o `summary.md` nelle tabelle Initiatives e Done): l'etichetta segue il titolo attuale del piano (ripulito da prefisso numerico e suffissi come `— Implementation plan`/`— Piano di implementazione`/`— Summary`/`— Riepilogo`), a meno che l'etichetta non sia curata a mano (diversa dal titolo attuale e da ogni titolo precedente estratto da `git log -p --follow -- <plan.md>`, oppure se non in repo git se non è prefisso o sottostringa del titolo).
- [x] Aggiunta opzione `sync-index --refresh-labels` per forzare l'allineamento delle etichette delle iniziative ai titoli attuali dei piani (anteprima mostra le modifiche; applicazione con hash abituale).
- [x] Le righe dei task emergenti mantengono inalterato il comportamento T050.

## Verification

- Test specifici T068 eseguiti con successo in `test_tasks_engine.py`:
  - `test_t068_clean_initiative_title`: pulizia corretta dei titoli di piano/riepilogo, rimozione di prefissi numerici e suffissi `— Implementation plan`, `— Piano di implementazione`, `— Summary`, `— Riepilogo`.
  - `test_t068_sync_index_initiative_labels_renamed_and_curated`: piano rinominato aggiorna l'etichetta con sync normale se il vecchio titolo è nella cronologia git; etichetta scritta a mano diversa da tutti i titoli passati viene mantenuta; le righe dei task emergenti rimangono invariate; `--refresh-labels` sovrascrive le etichette curate delle iniziative lasciando intatti i task.
  - `test_t068_sync_index_initiative_labels_non_git_repo`: in directory non-git le etichette prefisso/sottostringa seguono il titolo corrente, le etichette completamente diverse vengono mantenute come curate; `--refresh-labels` le forza.
  - `test_t068_sync_index_initiative_in_done_table`: le righe di iniziativa presenti nella tabella Done seguono le stesse regole (aggiornamento da storico git, mantenimento etichette curate, override con `--refresh-labels`).
- Test suite completa passata: `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` (241 passati su 241).
- Verifica reale: `sync-index --tasks-dir tasks` su questo repo non riporta modifiche alle iniziative (`Initiatives: +0 -0 ~0 row(s)`).

## Log (newest first)

- 2026-10-27, claude:ai-coding-tools: state `verified` -> `done` — verified by ai-coding-tools
- 2026-10-27, claude:ai-coding-tools: state `delivered` -> `verified` — OK on a scratch clone of ai-swissknife with architect-side 0.8.2: (1) plan.md title of 37 changed + commit -> sync --apply relabels the index row; (2) hand-written label kept by sync ('already in sync'); (3) --refresh-labels preview offers replacing the hand-written label with the plan title
- 2026-10-27, kilo: state `open` -> `delivered` — etichette delle iniziative allineate ai titoli correnti del piano con fallback git/curated e flag --refresh-labels
