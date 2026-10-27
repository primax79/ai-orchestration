# Riepilogo: 09 - Inbox: note in bozza, report e screenshot, elaborati in task

- **Rilasciato:** 2026-10-23
- **Piano:** [`plan.md`](plan.md)
- **Validazione:** chiuso in blocco il 2026-10-23 (verificatore: owner; "Validated by automated test suites and approved by owner for cleanup"); gli elementi contrassegnati "done with a caveat" non avevano una sessione utente per validarli.

## Esito

È stato rilasciato il sistema di acquisizione dell'inbox per raccogliere note in bozza, segnalazioni di bug, log e screenshot, e per convertirli in task strutturati. Le funzionalità includono il supporto del motore per le cartelle delle note e gli allegati, caricamenti autenticati nel backend, parità interattiva tra Web UI e VS Code, e proposte di triage automatico guidate da agenti.

- **09.1** — Motore: cartelle delle note, `ai-orch inbox ...`, `tasks new --from-note`: done
- **09.2** — Backend UI: endpoint dell'inbox con caricamenti autenticati: done
- **09.3** — Frontend: scheda Inbox, editor con incolla e trascinamento di immagini, "Convert to task" manuale: done
- **09.4** — Triage tramite agente: modalità di esecuzione `triage`, revisione della proposta, accettazione: done with a caveat: validated by the architect, no user yet
- **09.5** — Frontend: "Process with…" e revisione della proposta: done with a caveat: validated by the architect, no user yet
- **09.6** — VS Code: parità della scheda inbox (incolla e caricamento tramite postMessage): done
- **09.7** — Motore: allegati generici (testo, PDF), tipo `feature`, allegati dei task, la conversione copia gli allegati: done
- **09.8** — Backend UI: endpoint per gli allegati dei task e servizio distinto per classe: done with a caveat: validated by the architect, no user yet
- **09.9** — Frontend: allegati per classe nell'editor delle note e nel dettaglio del task: done
- **09.10** — Modifica dei task proposti prima di accettare una proposta di triage: done
- **09.11** — VS Code: handler per gli allegati dei task e il triage (parità con 09.5, 09.8, 09.9): done

## Deviazioni

L'ambito è stato esteso durante l'implementazione con i task 09.7–09.11 per supportare gli allegati generici non immagine (PDF e log) sia sulle note sia sui task, la modifica al volo dei task proposti dal triage prima dell'accettazione e la completa parità del bridge VS Code.

## Follow-up

Nessuno registrato nel piano.
