# T032 Le scritture da CLI raggiungono un broker attivo; la guardia ignora i manifest obsoleti

- id: T032
- title: Le scritture da CLI raggiungono un broker attivo; la guardia ignora i manifest obsoleti
- category: server-and-bindings
- priority: P1
- priority-reason: Quando un broker è attivo, tutte le sessioni prive dei tool MCP del broker (evolution-assurance, gcube-audit) non riescono più a scrivere i task
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: message from d4science-evolution-assurance-37, 2026-10-21; broker guard of 16.2
- paths: scripts/orchestration_broker_lock.py, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, bin/ai-orch
- handoff: Leggere tasks/server-and-bindings/T032-cli-writes-reach-a-live-broker-guard-ignores-a-sta.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- use-cases: UC032
- short: Scritture CLI tramite broker

## Goal

Mentre un broker attivo detiene broker.lock, un comando CLI mutante di ai-orch inoltra la scrittura al broker (tramite shim stdio o HTTP locale con il token della UI) e ne restituisce il risultato, anziché fallire con broker-owns-writes. La guardia considera il lock detenuto solo quando il pid del manifest è attivo e il suo messaggio non cita mai un pid terminato proveniente da un broker.json obsoleto. Nessuna sessione ha mai bisogno di AI_ORCH_BROKER_CHILD per scrivere.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
