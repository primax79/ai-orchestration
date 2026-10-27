# Riepilogo: 11 - Gerarchia di task di prima classe (N livelli)

- **Rilasciato:** 2026-10-23
- **Piano:** [`plan.md`](plan.md)
- **Validazione:** chiuso in blocco il 2026-10-23 (verificatore: owner; "Validated by automated test suites and approved by owner for cleanup"); gli elementi contrassegnati "done with a caveat" non avevano una sessione utente per validarli.

## Esito

Sono state introdotte gerarchie ricorsive di task a profondità arbitraria nel modello dei dati, nel motore e nell'interfaccia. L'implementazione fornisce transizioni atomiche sulle foglie, stati derivati per i contenitori, iniezione del contesto genitore durante l'esecuzione, normalizzazione dei piani legacy, archiviazione separata dei task chiusi e visualizzazioni ad albero comprimibili.

- **11.1** — Motore: parser ricorsivo dei nodi, ereditarietà, transizioni solo sulle foglie, stato derivato dei contenitori, dipendenze sui contenitori, comandi strutturali (`child add`, `expand`, `collapse`, `reopen`; nessun `move`, specifica S1): done
- **11.2** — Esecuzioni sui task figli: done
- **11.3** — UI: albero comprimibile a qualsiasi profondità, dettaglio del nodo con ereditarietà, aggiunta figlio, espansione, spostamento, breadcrumb: done
- **11.4** — Motore: collocazione separata dei chiusi a ogni livello (`tasks ship`, sezione `## Closed` per i blocchi, riscrittura dei link, `tasks archive`; le domande restano sul posto secondo S3): done
- **11.5** — Normalizzazione dei piani legacy: rilevamento, modalità di esecuzione `normalize`, preview/apply: done
- **11.6** — Follow-up della revisione di 11.1: applicazione di S10, `reopen` completo, figli di `T###`, test CLI: done

## Deviazioni

Il task 11.5 è stato aggiunto in seguito al feedback dell'owner sui piani legacy a formato libero per supportare il rilevamento e l'aggiornamento dei piani, mentre il task 11.6 è stato aggiunto per affrontare i follow-up della revisione sull'applicazione degli hash e sulla copertura dei test CLI.

## Follow-up

Nessuno registrato nel piano.
