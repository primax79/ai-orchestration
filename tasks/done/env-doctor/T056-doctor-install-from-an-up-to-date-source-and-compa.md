# T056 Doctor: installare da un sorgente aggiornato e confrontare il contenuto della skill, non l'hash memorizzato

- id: T056
- title: Doctor: installare da un sorgente aggiornato e confrontare il contenuto della skill, non l'hash memorizzato
- category: env-doctor
- priority: P1
- priority-reason: Kilo ha mantenuto skill di orchestrazione obsolete dopo un rilascio; il Doctor le segnalava come aggiornate
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N056 (ai-coding-tools, releasing architect-side 0.7.0)
- paths: scripts/orchestration_env.py
- handoff: Leggere tasks/env-doctor/T056-doctor-install-from-an-up-to-date-source-and-compa.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: ai-coding-tools-c1
- use-cases: UC011, UC012
- short: Installazione skill aggiornate

## Goal

install-skills e il report di stato confrontano il contenuto della skill installata con il contenuto sorgente (non il source_hash salvato in .ai-orch-source.json), così che una copia obsoleta venga mostrata come outdated e sostituita senza --overwrite; il Doctor segnala quando il suo clone sorgente (~/.ai-orchestration/repos/<repo>) è indietro rispetto al remote, o quando un checkout locale configurato è più recente, e propone fetch-repos (in anteprima); i test coprono entrambi i casi.

## Steps

- [x] Aggiornare `detect_skill_state` e `detect_agent_state` in `scripts/orchestration_env.py` per confrontare l'hash del contenuto installato con l'hash del contenuto sorgente corrente (`hash_directory` / `sha256`) anziché fidarsi del marker di installazione `source_hash`.
- [x] Classificare le copie pulite che corrispondono a versioni sorgente precedenti come `outdated`, distinguendole dalle copie modificate localmente (`modified-or-outdated`).
- [x] Aggiornare `install_skills` in modo che le copie `outdated` (sorgente più recente) pianifichino `REPLACE` con motivo `(source newer)` senza richiedere `--overwrite`, mentre le copie modificate localmente continuino a richiedere `--overwrite`.
- [x] Assicurarsi che il marker di ricevuta `.ai-orch-source.json` venga aggiornato con il `source_hash` corrente al momento della sostituzione/installazione.
- [x] Implementare il rilevamento dell'obsolescenza del clone sorgente in `scripts/orchestration_env.py` (`check_source_repo_stale`, `check_source_repo_behind_remote`, `check_local_checkout_ahead`): riportare avvisi in `env status` e `install-skills` quando `~/.ai-orchestration/repos/<repo>` è indietro rispetto al suo remote o quando un checkout locale configurato è avanti, proponendo `ai-orch env fetch-repos --repos <repo>`.
- [x] Aggiungere unit test in `scripts/test_orchestration_env.py` che coprano la sostituzione delle copie obsolete senza `--overwrite`, il mantenimento delle modifiche locali che richiedono `--overwrite`, l'aggiornamento dei marker durante l'installazione, l'avviso di remote indietro, la tolleranza offline e l'avviso di checkout locale più recente.

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/`: 563 passati in 381.60s.
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/test_orchestration_env.py`: 81 passati in 108.96s.
- Verifica live isolata in una directory temporanea di scratch: verificato che `install-skills` installa la v1, la modifica del sorgente nel clone di scratch aggiorna alla v2 e il successivo dry-run pianifica `REPLACE` con `(source newer)` senza `--overwrite`.

## Log (newest first)

- 2026-10-25, ai-coding-tools-c1: state `verified` -> `done` — Verifica del richiedente (indipendente dall'esecutore, kilo): il dry run in sola lettura sulla home reale mostra le skill di Kilo aggiornate senza REPLACE spuri e il nuovo avviso che il clone sorgente è indietro rispetto al remote; i test coprono la sostituzione delle copie obsolete senza --overwrite; suite completa 563 passati
- 2026-10-25, ai-coding-tools-c1: state `delivered` -> `verified` — Verifica del richiedente (indipendente dall'esecutore, kilo): il dry run in sola lettura sulla home reale mostra le skill di Kilo aggiornate senza REPLACE spuri e il nuovo avviso che il clone sorgente è indietro rispetto al remote; i test coprono la sostituzione delle copie obsolete senza --overwrite; suite completa 563 passati
- 2026-10-25, ai-coding-tools-c1: state `in progress` -> `delivered` — Verifica del richiedente (indipendente dall'esecutore, kilo): il dry run in sola lettura sulla home reale mostra le skill di Kilo aggiornate senza REPLACE spuri e il nuovo avviso che il clone sorgente è indietro rispetto al remote; i test coprono la sostituzione delle copie obsolete senza --overwrite; suite completa 563 passati
- 2026-10-25, ai-coding-tools-c1: state `open` -> `in progress` — Verifica del richiedente (indipendente dall'esecutore, kilo): il dry run in sola lettura sulla home reale mostra le skill di Kilo aggiornate senza REPLACE spuri e il nuovo avviso che il clone sorgente è indietro rispetto al remote; i test coprono la sostituzione delle copie obsolete senza --overwrite; suite completa 563 passati
