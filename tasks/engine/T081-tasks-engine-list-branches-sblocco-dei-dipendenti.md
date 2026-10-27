# T081 tasks_engine: list --branches, sblocco dei dipendenti e validate --branch

- id: T081
- title: tasks_engine: list --branches, sblocco dei dipendenti e validate --branch
- category: engine
- priority: P2
- priority-reason: L'architetto ricostruisce a mano le tabelle dei branch e sblocca a mano i task dipendenti (D.1, D.3, D.4)
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: lezioni di ricerca_auto 2026-10-17, analisi T078 (ai-orchestration/tasks/_reviews/2026-10-27-ricerca-auto-lessons-triage.md)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T081-tasks-engine-list-branches-sblocco-dei-dipendenti.md, do the open steps, run the Verification, update the task and the registry.
- short: Branch e sblocco dipendenti

## Goal

tasks list --branches mostra per i task attivi branch, commit avanti, file sporchi e stato scritto sul branch; quando un task va in done, i task bloccati con tutte le dipendenze chiuse vengono proposti per lo sblocco (unblock-ready); validate --branch controlla un branch prima del merge.

## Steps

- [ ] Implementazione e test

## Verification

- Test sui tre comandi con worktree finti
