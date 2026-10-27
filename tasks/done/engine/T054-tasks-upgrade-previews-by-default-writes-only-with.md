# T054 tasks upgrade mostra l'anteprima per impostazione predefinita; scrive solo con --apply e un hash del piano

- id: T054
- title: tasks upgrade mostra l'anteprima per impostazione predefinita; scrive solo con --apply e un hash del piano
- category: engine
- priority: P1
- priority-reason: Il comando 'upgrade' semplice scrive AGENTS.md e l'indice senza anteprima, violando la convenzione preview-then-apply; rilevato durante la verifica di T050
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: ai-coding-tools review of T050 (2026-10-25)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T054-tasks-upgrade-previews-by-default-writes-only-with.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: ai-coding-tools-c1
- short: Anteprima predefinita in upgrade

## Goal

'ai-orch tasks upgrade' senza --apply stampa il piano (i file da creare o modificare, con un riepilogo del diff) e l'hash del piano senza scrivere nulla; '--apply --expect-plan-hash H' effettua la scrittura; '--dry-run' e '--preview' restano come alias del comportamento predefinito; la skill, il blocco gestito di AGENTS.md e il testo di aiuto lo documentano; i test coprono l'assenza di scritture per impostazione predefinita e il rifiuto di apply con un hash obsoleto.

## Steps

- [x] Ispezionare `cmd_upgrade`, `upgrade_tasks_tree` e i subparser degli argomenti CLI in `tasks_engine.py`.
- [x] Aggiornare `compute_operation_plan` per includere `summary` nell'output del piano mantenendo l'hash canonico su `(action, before_hash, path)`.
- [x] Modificare `upgrade_tasks_tree` per supportare `apply: bool | None` e `expect_plan_hash`, verificando l'hash del piano prima di eseguire modifiche su disco e restituendo `applied: True/False`.
- [x] Aggiornare `cmd_upgrade` per mostrare l'anteprima per impostazione predefinita senza `--apply`, stampando i riepiloghi dei diff del piano, l'hash del piano e `To apply: ai-orch tasks upgrade ...`, e richiedendo `--apply --expect-plan-hash <hash>` per scrivere.
- [x] Aggiornare `is_mutating_command` affinché consideri `upgrade` mutante solo quando è presente `--apply` (e non in modalità preview/dry-run).
- [x] Aggiornare il testo di aiuto e la documentazione in `bin/ai-orch` e `SKILL.md`.
- [x] Aggiornare i test di upgrade esistenti per usare `--apply --expect-plan-hash` e aggiungere `test_t054_upgrade_previews_by_default_and_applies_only_with_plan_hash`.
- [x] Verificare il comportamento dal vivo su una copia temporanea di `porting_liferay/tasks` con git status pulito sull'upgrade semplice e le modifiche attese con apply.

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py` (194 passati)
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_feedback.py` (11 passati)
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/shared/skills/orchestration-setup/scripts/` (tutti passati)
- Test dal vivo su una copia temporanea di `~/works/gcube/porting_liferay/tasks`:
  - L'upgrade semplice stampa il riepilogo dei diff e l'hash del piano senza modificare il disco (`git status` pulito).
  - L'applicazione senza hash viene rifiutata con codice 1 (`git status` pulito).
  - L'applicazione con hash obsoleto viene rifiutata con codice 1 (`git status` pulito).
  - L'applicazione con l'hash del piano applica le modifiche in modo pulito con codice 0.

## Log (newest first)

- 2026-10-25, orchestrator: state `verified` -> `done` — Verificato dal richiedente
- 2026-10-25, ai-coding-tools-c1: state `delivered` -> `verified` — Verifica del richiedente (indipendente dall'executor, kilo): su una copia temporanea di porting_liferay/tasks, l'upgrade semplice non ha scritto nulla e ha stampato un hash; --apply senza hash e con hash errato sono stati rifiutati; --apply con l'hash ha scritto i 2 file; intera suite 558 passati
