# Riepilogo: 08 - Domande bloccanti (formato, motore, UI delle risposte in sospeso)

- **Rilasciato:** 2026-10-23
- **Piano:** [`plan.md`](plan.md)
- **Validazione:** chiuso in blocco il 2026-10-23 (verificatore: owner; "Validated by automated test suites and approved by owner for cleanup"); gli elementi contrassegnati "done with a caveat" non avevano una sessione utente per validarli.

## Esito

Sono state introdotte le domande bloccanti strutturate per consentire agli agenti autonomi e agli sviluppatori di mettere in pausa l'esecuzione fino a quando non vengono prese decisioni architetturali umane. L'iniziativa ha fornito il formato dei file delle domande e la relativa validazione nel motore, i comandi CLI (`ai-orch questions`), le integrazioni nella dashboard della UI e di VS Code e le notifiche toast con badge.

- **08.1** — Motore: file delle domande, validatore, `ai-orch questions list|show|ask|answer|withdraw`, regione Decisions dalle domande aperte: done
- **08.2** — Skill: gli agenti registrano le domande bloccanti nel formato previsto: done
- **08.3** — Backend UI: endpoint delle domande: done
- **08.4** — Frontend: scheda Decisions, badge nella navbar, sezione Questions nella modale del task, modulo di invio domanda: done
- **08.5** — VS Code: albero "Decisions Waiting" dai file delle domande: done
- **08.6** — "Rispondi e riprendi l'esecuzione": done
- **08.7** — VS Code: notifica toast per le nuove domande e badge nella barra di stato: done

## Deviazioni

Le modifiche successive alla revisione 2 (Q1–Q10) hanno affinato i requisiti e le dipendenze nei task 08.1–08.6. La registrazione delle domande da parte del supervisore in 08.6 è stata spostata al task 07.10, mentre la ripresa delle esecuzioni è stata coordinata con l'iniziativa 12 (task 12.4). Il task 08.7 è stato aggiunto in seguito a una richiesta dell'owner per le notifiche toast e il badge nella barra di stato di VS Code.

## Follow-up

Nessuno registrato nel piano.
