# Riepilogo: 07 - Esecuzioni degli agenti dal piano di controllo (scegliere chi svolge il lavoro)

- **Rilasciato:** 2026-10-23
- **Piano:** [`plan.md`](plan.md)
- **Validazione:** chiuso in blocco il 2026-10-23 (verificatore: owner; "Validated by automated test suites and approved by owner for cleanup"); gli elementi contrassegnati "done with a caveat" non avevano una sessione utente per validarli.

## Esito

Le funzionalità di esecuzione e supervisione end-to-end degli agenti sono state integrate nel piano di controllo, nella CLI, nella UI e nel bridge VS Code. Il motore di esecuzione fornisce isolamento tramite worktree, modalità di esecuzione e verifica, supervisione dei processi con annullamento pulito, cattura delle domande bloccanti e modifica della configurazione per il routing e le allow-list dei tool.

- **07.1** — `config set-routing`, aggiornatore TOML chirurgico, schema `[tools.<t>.headless]`, testo corretto per il percorso di configurazione del progetto: done
- **07.2** — Motore di esecuzione A: registro, locking, record, validazione delle richieste, prompt, `options`/`preview`/`list`/`show`: done
- **07.3** — Motore di esecuzione B: supervisore, adapter (prompt via stdin/file), annullamento e riconciliazione delle esecuzioni perse con terminazione del gruppo di processi: done
- **07.4** — Motore di esecuzione C: isolamento worktree, target di verifica, parsing del verdetto e `apply-verdict`, invarianti di continuazione, `cleanup`: done
- **07.5** — Cattura dal vivo con le vere CLI: id di sessione, Final Report, verdetto, continue; correzione della tabella dei flag: done with a caveat: validated by the architect, no user yet
- **07.6** — Backend UI: endpoint di esecuzione e di configurazione: done
- **07.7** — Frontend: finestra di dialogo Run con anteprima dal vivo, pannello delle esecuzioni del task, scheda Runs: done
- **07.8** — Frontend: modifica nella scheda Config (routing e matrice profilo/modello): done
- **07.9** — VS Code: handler delle esecuzioni e watcher delle esecuzioni: done
- **07.10** — Core: il supervisore delle esecuzioni registra le domande bloccanti (R14, specifica 08 Q8): done
- **07.11** — Esecuzioni batch per i microtask: done with a caveat: validated by the architect, no user yet
- **07.12** — Allow-list integrata per modalità per Claude (decisione A di Q001): done

## Deviazioni

Le modifiche successive alla revisione 2 (R1–R14) hanno esteso i task 07.1–07.5, 07.8 e 07.9. La decisione A della domanda Q001 ha introdotto il task 07.12 (allow-list di tool integrate per modalità per Claude), mentre il task 07.11 è stato aggiunto per gestire l'esecuzione batch dei microtask prevista dalla specifica della timeline.

## Follow-up

Nessuno registrato nel piano.
