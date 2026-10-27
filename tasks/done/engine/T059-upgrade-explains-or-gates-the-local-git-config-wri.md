# T059 upgrade spiega o subordina a opzione la scrittura nella configurazione git locale del merge driver dell'indice

- id: T059
- title: upgrade spiega o subordina a opzione la scrittura nella configurazione git locale del merge driver dell'indice
- category: engine
- priority: P3
- priority-reason: Già dichiarato nel piano; nota del richiedente, non bloccante
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: porting-liferay-8c, T050 re-check 2026-10-25, note (a)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Leggi tasks/engine/T059-upgrade-explains-or-gates-the-local-git-config-wri.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- short: Opt-in del merge driver

## Goal

upgrade scrive merge.ai-orch-index.driver in .git/config del repo di destinazione con un percorso assoluto nella home dell'utente. Renderlo esplicito: o tramite un flag di opt-in (ad es. --register-merge-driver, attivo per impostazione predefinita solo quando il launcher è in PATH) oppure tramite una riga di anteprima che spieghi cosa viene scritto, che è locale a questo clone e cosa succede su una macchina senza ai-orch (git ripiega sul normale merge testuale). Coordinarsi con T058 (percorso del driver pendente).

## Steps

- [x] Aggiungere `--skip-git-config` (`--no-git-config`) a `tasks upgrade` e stampare una nota esplicativa quando `.git/config` compare nel piano di upgrade.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k upgrade`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, owner: state `delivered` -> `verified` — Implementato e verificato con test di regressione pytest automatizzati
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
