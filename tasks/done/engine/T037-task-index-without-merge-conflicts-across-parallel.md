# T037 Indice dei task senza conflitti di merge tra branch paralleli

- id: T037
- title: Indice dei task senza conflitti di merge tra branch paralleli
- category: engine
- priority: P1
- priority-reason: Modifica prioritaria per gcube-audit: ogni merge parallelo va in conflitto su 00-INDEX.md, con righe duplicate e in un caso una risposta persa
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: feedback round 2026-10-21: inbox N002
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Leggi tasks/tasks/T037-task-index-without-merge-conflicts-across-parallel.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: owner
- verify-by: gcube_audit
- short: Indice senza conflitti

## Goal

Il merge di due branch che hanno ciascuno aggiunto dei task non richiede mai di risolvere a mano 00-INDEX.md: ad es. un merge driver di git registrato da 'tasks upgrade' (.gitattributes + git config locale) che rigenera le sezioni generate con sync-index dopo il merge, oppure sezioni dell'indice ricostruite su richiesta. Prima progettare (breve sezione di specifica con confronto tra le opzioni), poi implementare; i file delle domande non vengono mai toccati dalla rigenerazione dell'indice. Inoltre (inbox N037): un task delegato viene registrato nell'albero condiviso (riga visibile, stato in progress) prima dell'avvio dell'esecuzione, non solo al momento del merge. sync-index ricostruisce le tabelle generate a partire dagli header, così le righe duplicate lasciate da un merge scompaiono (inbox N040, gcube_audit; osservato con una copia vendored, verificare prima il comportamento attuale).

## Steps

- [x] Registrare `merge.ai-orch-index.driver` e `merge.ai-orch-index.name` nella configurazione git locale durante `upgrade` (mostrato nell'anteprima del piano e applicato con `--apply --expect-plan-hash`), emettere un avviso in `validate` quando `.gitattributes` indica `merge=ai-orch-index` senza il driver nella configurazione git, e documentare la configurazione in `task-pipeline/SKILL.md`.
- [x] Implementare il merge a 3 vie a livello di riga per le tabelle + il merge testuale a 3 vie per le parti non generate in `merge_index_three_way` / `cmd_merge_index` (`%O %A %B`).
- [x] Stampare il piè di pagina di dry-run `"preview only, nothing written; re-run with --apply"` in `sync-index` senza `--apply`.

## Verification

- [x] I test unitari e di integrazione in `test_tasks_engine.py` passano (`209 passed`).
- [x] La verifica dal vivo in un repo git temporaneo nella directory temporanea di sistema con due branch che aggiungono task ed eseguono `sync-index --apply` esegue il merge in modo pulito con zero conflitti, entrambe le righe presenti e zero duplicati.

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Punti riaperti verificati in test_tasks_engine.py + controllo dal vivo su repo temporaneo; chiusura approvata dall'owner
- 2026-10-25, owner: state `delivered` -> `verified` — Punti riaperti verificati in test_tasks_engine.py + controllo dal vivo su repo temporaneo; chiusura approvata dall'owner
- 2026-10-25, kilo: state `open` -> `delivered` — Risolti i rilievi della riapertura: `upgrade` registra `merge.ai-orch-index.driver` e `merge.ai-orch-index.name` nella configurazione git locale (e lo mostra nel piano), `validate` avvisa quando `.gitattributes` contiene `merge=ai-orch-index` senza il driver nella configurazione git, `merge-index %O %A %B` esegue un merge di unione a 3 vie a livello di riga delle tabelle generate e un merge testuale a 3 vie fuori dalle regioni generate, e `sync-index` senza `--apply` stampa il piè di pagina di dry-run (209 passati)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzati e approvato dall'owner per la pulizia
- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Eseguito merge di d70d453; verificati 00-INDEX.md senza conflitti, il driver merge-index e tasks/.gitattributes durante upgrade (169 passati)
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Assegnazione di T037 (Indice senza conflitti tra worktree paralleli) a Kilo

## Riapertura 2026-10-25 (validazione del richiedente, gcube-audit)

Configurazione: due branch aggiungono ciascuno un task valido + `sync-index --apply`; tasks/.gitattributes contiene `00-INDEX.md merge=ai-orch-index`.
NON OK:
1. Nulla imposta la configurazione git `merge.ai-orch-index.driver` e nessun documento la menziona, quindi il merge va comunque in CONFLITTO.
   `upgrade` scrive solo .gitattributes. Registrare il driver (in upgrade, con anteprima; oppure documentare una configurazione di una riga)
   e fare in modo che `validate` avvisi quando .gitattributes indica il driver ma questo manca nella configurazione git.
2. Configurando il driver a mano (`ai-orch tasks merge-index %O %A %B`), il merge non presenta conflitti ma scarta
   la riga di theirs (viene mantenuta solo la riga di ours); un successivo `sync-index --apply` la ripristina. Il driver deve rigenerare a partire dagli
   header uniti, non mantenere un solo lato.
OK: le righe duplicate vengono collassate da `sync-index --apply`.
Minore: `sync-index` senza `--apply` stampa l'intero indice come dry run; è facile scambiarlo per "fatto". Stampare un piè di pagina di una riga
"preview only, nothing written; re-run with --apply".
Verificare di nuovo con il richiedente prima di chiudere.
