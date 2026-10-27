# T067 transition mantiene la nota Status esistente dei task di iniziativa

- id: T067
- title: transition mantiene la nota Status esistente dei task di iniziativa
- category: engine
- priority: P2
- priority-reason: La chiusura di 148 task di ai-swissknife ha cancellato lo sha di merge (l'evidenza) da ogni blocco del piano
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-105658-transition-to-done-replaces-the-status-n/note.md
- paths: -
- handoff: Leggi tasks/engine/T067-transition-keeps-the-existing-status-note-of-initi.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: claude:ai-coding-tools
- verify-by: ai-coding-tools
- short: Mantenere evidenza in Status

## Goal

In ai-swissknife (2026-10-27) i blocchi dei task di iniziativa avevano '- **Status:** `delivered` (merged <sha> <date>)'. Il comando 'tasks transition <id> done --verifier X' ha riscritto la nota in '(2026-10-27; X)', facendo sparire lo sha di merge (l'evidenza) da plan.md; l'ho recuperato dalla cronologia git per i riepiloghi. Comportamento atteso: mantenere la nota esistente e accodare la chiusura ('merged <sha> <date>; done 2026-10-27, verifier X'), oppure spostare la vecchia nota in una riga di Log.

## Steps

- [x] transition su un blocco di task di iniziativa mantiene la nota esistente e accoda il nuovo evento ('merged <sha> <date>; done 2026-10-27, verifier X'), gestendo passaggi intermedi del walk senza duplicazioni ed evitando note > ~200 caratteri preservando primo evento e ultimo

## Verification

- Test: un blocco con '(merged abc123 2026-10-08)' portato a done tramite transition mantiene abc123 in plan.md:
  `test_t067_initiative_task_status_note_evidence_and_closure` eseguito con successo, preserva lo sha e accoda `done <date>, verifier auditor`.
- Test suite completa: `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` terminata con 237 test passati su 237.
- Test specifici T067:
  - `test_t067_initiative_task_status_note_evidence_and_closure`: blocco con nota esistente mantiene sha e accoda evento di chiusura; blocco senza nota riceve solo l'evento di chiusura.
  - `test_t067_initiative_task_walk_produces_single_event`: walk da `in progress` e da `open` genera un unico evento accodato per lo stato finale senza eventi intermedi.
  - `test_t067_initiative_task_reopen_keeps_history_note`: riapertura mantiene la cronologia preesistente accodando l'evento di riapertura.
  - `test_t067_initiative_task_note_truncation_over_200_chars`: se la nota supera ~200 caratteri, mantiene la prima nota (evidenza) e l'ultimo evento, eliminando quelli intermedi su una singola riga.

## Log (newest first)

- 2026-10-27, claude:ai-coding-tools: state `verified` -> `done` — verified by ai-coding-tools
- 2026-10-27, claude:ai-coding-tools: state `delivered` -> `verified` — OK: on a scratch copy of ai-swissknife/tasks with architect-side 0.8.1: 37.2 delivered with '(merged abc1234 2026-10-27)' -> done gives '(merged abc1234 2026-10-27; done 2026-10-27, verifier claude:ai-coding-tools)'; walk from in progress keeps the note with one final entry; >200-char note keeps first entry and last event. Note: the event log still records one task.transitioned per step (delivered->verified, verified->done); the single entry applies to the Status note, as the T067 tests define
- 2026-10-27, kilo: state `open` -> `delivered` — preservata l'evidenza delle note Status nei blocchi di iniziativa e aggiunti test T067
