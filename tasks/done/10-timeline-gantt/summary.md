# Riepilogo: 10 - Timeline astratta: dipendenze e priorità

- **Rilasciato:** 2026-10-23
- **Piano:** [`plan.md`](plan.md)
- **Validazione:** chiuso in blocco il 2026-10-23 (verificatore: owner; "Validated by automated test suites and approved by owner for cleanup"); gli elementi contrassegnati "done with a caveat" non avevano una sessione utente per validarli.

## Esito

Sono stati implementati il tracciamento delle dipendenze, l'ordinamento topologico in colonne e le pipeline di esecuzione guidate dalla priorità per il grafo dei task. Il sistema ha aggiunto il rilevamento dei cicli, il calcolo del percorso critico, i microtask con intestazioni ridotte e molteplici viste del backlog (Queue, Kanban, Tree e Timeline) nella Web UI e in VS Code.

- **10.1** — Motore: `tasks graph` (colonne, coda pronta, catena più pesante, Mermaid), campo `size`, `tasks set-priority`, `tasks set-size`, `tasks set-deps`, controllo dei cicli: done
- **10.2** — UI: endpoint del grafo e di modifica e scheda Timeline (frecce, coda pronta, modifica di priorità e dipendenze): done
- **10.3** — VS Code: Timeline nella webview: done
- **10.4** — Motore: microtask (categoria `micro`, schema ridotto, `tasks micro`, `tasks promote`, dimensione XS), tipo ed etichette: done
- **10.5** — UI: aggiunta rapida di microtask, pillole XS, "Promote", tipo ed etichette, barra dei filtri condivisa: done
- **10.6** — Viste del Backlog: "Next up" compatto, selettore di vista separato (Queue, Kanban, Tree, Timeline): done

## Deviazioni

Il task 10.6 è stato introdotto sulla base del feedback dell'owner per sostituire la vista monolitica Next Up con una coda compatta (Queue) e un selettore persistente multi-vista.

## Follow-up

Nessuno registrato nel piano.
