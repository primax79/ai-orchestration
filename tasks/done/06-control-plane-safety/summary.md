# Riepilogo: 06 - Sicurezza del piano di controllo (Doctor, indice, backend UI, bridge VS Code)

- **Rilasciato:** 2026-10-23
- **Piano:** [`plan.md`](plan.md)
- **Validazione:** chiuso in blocco il 2026-10-23 (verificatore: owner; "Validated by automated test suites and approved by owner for cleanup"); gli elementi contrassegnati "done with a caveat" non avevano una sessione utente per validarli.

## Esito

L'irrigidimento della sicurezza e dell'integrità del piano di controllo è stato completato attraverso il Doctor, la sincronizzazione dell'indice, il backend della UI e il bridge dell'estensione VS Code. Le modifiche hanno introdotto marcatori di regione generata per la sincronizzazione senza perdite dell'indice, piani dry-run con hash del contenuto, inventario consapevole dei plugin e ispezione dei veri file di configurazione MCP nel Doctor, esecuzione non bloccante autenticata nel backend UI e lock esclusivi di scrittura sui task.

- **06.1** — `sync-index` senza perdita di dati con marcatori delle regioni generate (I1–I4): done
- **06.2** — Doctor: piani `--dry-run` con hash, installazione senza sovrascrittura, cestino invece di eliminazione, pulizia esplicita degli obsoleti (E4, E6, E7): done
- **06.3** — Doctor: inventario e conflitti consapevoli dei plugin (E5): done
- **06.4** — Doctor: registrazione e stato MCP tramite i veri file di configurazione (E3): done
- **06.5** — Backend UI: autenticazione, chiamate CLI non bloccanti, workspace fisso, watcher (U1, U4, U5, U6): done
- **06.6** — Core: `render-agents-md --diff` con precondizione sull'hash: done
- **06.7** — Backend UI: endpoint preview/apply; le transizioni non scrivono più l'indice (U2, U3): done
- **06.8** — Frontend: modale di conferma con anteprime, impostazioni predefinite più sicure per l'installatore, origini del Doctor, banner di errore, riconnessione WS (U3, U7, V3): done
- **06.9** — Bridge VS Code: mappa completa degli handler, rifiuto su codice diverso da zero, sincronizzazione `dist-webview`, nessun percorso cablato, scelta multi-root (V1, V2): done
- **06.10** — Core: lock di scrittura sui task, `--expect-task-hash`, scritture atomiche (A9): done

## Deviazioni

Le modifiche successive alla revisione 2 (A1–A12) hanno esteso l'ambito dei task 06.2–06.9 e aggiunto il task 06.10 per i lock di scrittura sui task e le scritture atomiche. La funzionalità `set-routing`/`set-profile` `--diff`/`--expect-hash`, inizialmente prevista per 06.6, è stata trasferita a 07.1.

## Follow-up

Nessuno registrato nel piano.
