# T067 transition mantiene la nota Status esistente dei task di iniziativa

- id: T067
- title: transition mantiene la nota Status esistente dei task di iniziativa
- category: engine
- priority: P2
- priority-reason: La chiusura di 148 task di ai-swissknife ha cancellato lo sha di merge (l'evidenza) da ogni blocco del piano
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-105658-transition-to-done-replaces-the-status-n/note.md
- paths: -
- handoff: Leggi tasks/engine/T067-transition-keeps-the-existing-status-note-of-initi.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verify-by: ai-coding-tools
- short: Mantenere evidenza in Status

## Goal

In ai-swissknife (2026-10-27) i blocchi dei task di iniziativa avevano '- **Status:** `delivered` (merged <sha> <date>)'. Il comando 'tasks transition <id> done --verifier X' ha riscritto la nota in '(2026-10-27; X)', facendo sparire lo sha di merge (l'evidenza) da plan.md; l'ho recuperato dalla cronologia git per i riepiloghi. Comportamento atteso: mantenere la nota esistente e accodare la chiusura ('merged <sha> <date>; done 2026-10-27, verifier X'), oppure spostare la vecchia nota in una riga di Log.

## Steps

- [ ] transition su un blocco di task di iniziativa mantiene la nota esistente e accoda il nuovo evento ('merged <sha> <date>; done 2026-10-27, verifier X'), oppure sposta la vecchia nota nel log del blocco

## Verification

- Test: un blocco con '(merged abc123 2026-10-08)' portato a done tramite transition mantiene abc123 in plan.md
