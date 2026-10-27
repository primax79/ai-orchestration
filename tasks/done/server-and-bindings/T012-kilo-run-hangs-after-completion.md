# T012 kilo-mcp: rilevare i processi `kilo run` che restano bloccati dopo il completamento

- id: T012
- title: kilo-mcp: rilevare i processi kilo run che restano bloccati dopo il completamento
- category: server-and-bindings
- priority: P2
- priority-reason: I task bloccati risultano "running" per ore, nascondono il lavoro completato e mantengono vivi i processi; l'orchestratore se ne è accorto solo dagli mtime dei log
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: session 2026-10-17: tasks b7d26daa26b6, c7b5f7011bdf, b3cccdf3051e, ae7733625e86 committed and wrote their Final Report around 00:33–00:47, but their `kilo run` processes stayed alive and idle until cancelled at 10:10
- paths: ../kilo-mcp/server.py
- handoff: Leggere tasks/server-and-bindings/T012-kilo-run-hangs-after-completion.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: claude:orchestration
- short: Processi kilo run bloccati

## Goal

Quando `kilo run` ha terminato il proprio lavoro (il suo flusso di eventi JSON ha emesso il messaggio finale / evento di inattività della sessione) ma il processo non termina, kilo-mcp se ne accorge, registra l'esito e termina il processo. `kilo_task_progress`/`kilo_task_status` non devono riportare un task simile come in esecuzione.

## Steps

1. Riprodurre: verificare cosa emette `kilo run --format json` alla fine di una sessione (ispezionare il log di un task bloccato sotto `~/.local/share/kilo-mcp/tasks/`) e se il blocco è correlato a qualcosa di specifico (un processo figlio MCP che non termina mai, una shell in background).
2. Nel watcher dei task: dopo un evento terminale (o dopo il parsing del Final Report) più un periodo di tolleranza (ad es. 60 s) senza nuovo output, contrassegnare il task come completato e terminare il gruppo di processi.
3. `kilo_task_progress` riporta `finished, process lingering` invece di "no session found" durante il periodo di tolleranza.

## Verification

- Uno unit test con uno stub di `kilo` che stampa un evento finale e poi resta in attesa all'infinito: il task diventa `completed` entro il periodo di tolleranza e lo stub viene terminato.
- Un'esecuzione live di un task banale termina o viene raccolta entro il periodo di tolleranza.
