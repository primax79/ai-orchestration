# T001 Attesa di completamento dei task (`kilo_task_wait`) e linee guida per il watcher

- id: T001
- title: Attesa di completamento dei task (kilo_task_wait) e linee guida per il watcher
- category: server-and-bindings
- priority: P1
- priority-reason: Elimina i turni sprecati in polling e i task completati ma non segnalati nelle deleghe in background
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../task-completion-notification-spec.md, docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../kilo-mcp/server.py, ../kilo-mcp/test_server.py, ../kilo-mcp/bindings/orchestration-methodology.json, ../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md
- handoff: Leggere tasks/server-and-bindings/T001-task-completion-wait-and-watcher.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Guida attesa task

## Goal

Aggiungere `kilo_task_wait(task_id, timeout_seconds=None)` a `kilo-mcp/server.py` (con riconciliazione completa da crash/file di log tramite `_reconcile_task_if_orphaned`) e aggiornare le skill di orchestrazione (`orchestration-methodology` + `kilo-mcp-orchestrator`) affinché i task in background vengano attesi in modo deterministico (documentando il watcher PID da shell come fallback per i client privi di supporto per l'attesa bloccante).

## Steps

1. In `../kilo-mcp/server.py`, implementare `@mcp.tool() async def kilo_task_wait(task_id: str, timeout_seconds: int | None = None) -> str` che attende finché il task non raggiunge uno stato terminale (riconciliando ad ogni controllo i PID rimasti orfani a partire dai file di log), restituendo lo stesso payload di `kilo_task_result` o uno stato chiaro "still running" in caso di timeout senza sollevare eccezioni.
2. Aggiungere unit test in `../kilo-mcp/test_server.py` che coprano il completamento normale, il timeout e un task il cui processo di avvio è terminato a metà esecuzione (recupero da file di log).
3. Aggiornare la Fase 4 di `../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md` e `../kilo-mcp/bindings/orchestration-methodology.json` per istruire ad attendere il completamento tramite `kilo_task_wait` (o il fallback del watcher PID in background `while kill -0 <pid> 2>/dev/null; do sleep 10; done`) invece del polling a timer.
4. Rigenerare le skill generiche e associate e aggiornare `../kilo-mcp/README.md`, `ARCHITECTURE.md` e `SPEC_MCP_ORCHESTRATION.md`.

## Verification

- `../kilo-mcp/.venv/bin/pytest ../kilo-mcp/test_server.py` passa inclusi i nuovi test per `kilo_task_wait`.
- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` termina con codice 0.
