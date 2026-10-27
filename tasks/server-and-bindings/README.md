# server-and-bindings

owner-session: unassigned

## Obiettivo e ambito

Evoluzioni lato server in `../kilo-mcp/server.py` (attesa bloccante di completamento `kilo_task_wait`, telemetria delle decisioni `kilo_log_decision`, gate di verifica strutturato) e nuovi binding Executor (spike di Fase 1 e server in `../claude-mcp/`, valutazione di Pi). Stato e priorità dei relativi task si trovano in `tasks/00-INDEX.md`; le note di lavoro sono in `notes/` accanto a questo file.

## Avviare una sessione sull'intera categoria

> Leggere tasks/server-and-bindings/README.md e i relativi task in ordine di priorità, impostare owner-session, lavorare i task uno alla volta (prima i P0) e mantenere aggiornati i file dei task, questo README e tasks/00-INDEX.md.

## Regole

- Solo la sessione proprietaria modifica i file dei task e questo README; le altre aggiungono note qui sotto o creano nuovi task T###.
- Un task completato viene spostato con `git mv` in `tasks/done/server-and-bindings/`, mantenendo lo stesso nome.

## Note condivise
