# Riepilogo: 12 - Eventi, sessioni di orchestrazione e trigger

- **Rilasciato:** 2026-10-23
- **Piano:** [`plan.md`](plan.md)
- **Validazione:** chiuso in blocco il 2026-10-23 (verificatore: owner; "Validated by automated test suites and approved by owner for cleanup"); gli elementi contrassegnati "done with a caveat" non avevano una sessione utente per validarli.

## Esito

È stato costruito un livello di orchestrazione guidato dagli eventi dotato di archivio eventi outbox, gestione delle sessioni, motore dei trigger e ruolo di orchestratore headless. Il sistema registra le transizioni di stato, supporta trigger reattivi automatici (come la ripresa automatica delle esecuzioni quando si risponde alle domande) e fornisce flussi di eventi dal vivo e controlli di chat nella Web UI e in VS Code.

- **12.1** — Dati sulla ripresa headless (unito in 07.5): done with a caveat: validated by the architect, no user yet
- **12.3** — Registro delle sessioni e identificatori: done
- **12.4** — Motore dei trigger: done
- **12.5** — Ruolo di orchestratore headless (sessioni, coda, turni, successione, limiti): done with a caveat: validated by the architect, no user yet
- **12.6** — UI: flussi degli eventi e della coda, area notifiche, pagina Triggers, chip delle sessioni, gruppo "awaiting application": done
- **12.7** — VS Code: watcher degli eventi e notifiche: done
- **12.8** — UI: pannello chat dell'orchestratore: done
- **12.9** — Configurazione dell'orchestratore: riassegnazione come successione, motore `ai-orch setup` condiviso con la skill `orchestration-setup`: done with a caveat: validated by the architect, no user yet
- **12.10** — UI: scheda Orchestrator in Config (titolare attuale, Reassign…, pausa/rotazione) e procedura guidata di primo setup: done
- **12.11** — Core: archivio degli eventi (outbox, contatore, manifesto dei chunk, riconciliazione, `events tail`): done
- **12.12** — Emissione degli eventi da `tasks_engine.py`: done
- **12.13** — Emissione degli eventi da `orchestration_runs.py` ed estrazione della primitiva di invocazione supervisionata: done
- **12.14** — Emissione degli eventi da `orchestration_config.py`; scritture della configurazione sotto lock: done
- **12.15** — VS Code: handler di parità per i tipi di messaggio di 12.6 (sessioni, trigger, azioni proposte, notifiche, in attesa di applicazione): done
- **12.16** — UI: conferma/rifiuto delle azioni proposte dai trigger (collegamento T024) e ordinamento dei turni della chat: done
- **12.17** — VS Code: handler di parità per i tipi di messaggio di 12.8, 12.10 e 12.16 (chat dell'orchestratore, scheda Config e wizard, conferma/rifiuto proposte): done

## Deviazioni

I task 12.2a–12.2d sono stati rinumerati in 12.11–12.14 per conformarsi alla validazione numerica degli ID. Il task 12.1 è stato unito nella cattura dal vivo delle CLI (07.5). I task 12.15–12.17 sono stati aggiunti per la parità del bridge VS Code e la conferma interattiva delle proposte dei trigger.

## Follow-up

Nessuno registrato nel piano.
