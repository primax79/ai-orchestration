# T077 Le note dell'inbox in formato vecchio vengono adottate con un id

- id: T077
- title: Le note dell'inbox in formato vecchio vengono adottate con un id
- category: engine
- priority: P2
- priority-reason: Una nota del 2026-10-17 è rimasta 10 giorni non smistata; nella UI compare con id '-' e Process with fallisce
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: screenshot del proprietario 2026-10-27: Triage Note fallisce con Invalid note ID '-'
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, ai-orchestration-ui/frontend
- handoff: Read tasks/engine/T077-le-note-dell-inbox-in-formato-vecchio-vengono-adot.md, do the open steps, run the Verification, update the task and the registry.
- short: Adozione note vecchie

## Goal

I file .md piatti in _inbox (formato precedente alle note con header) diventano note vere con id N###, senza perdere il contenuto; la UI non offre azioni che richiedono l'id a una nota non adottata.

## Steps

- [ ] inbox adopt (anteprima/apply): file piatto -> cartella nota con header (id N### nuovo, title dal primo titolo, kind note, status ready, created dalla data del file); upgrade lo propone; validate segnala le note senza id
- [ ] UI: nota senza id mostra 'legacy: adopt' e disabilita Process with e Convert finché non è adottata

- [ ] `inbox resolve` accetta anche una nota già in `analyzed/` con status ancora `ready` (oggi rifiuta: caso N062) e ne registra produced/processed-by

## Verification

- Test: file piatto adottato -> N### con lo stesso corpo; la UI non offre Process su una nota senza id
