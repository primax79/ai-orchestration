# T071 Le sessioni che orchestrano vengono invitate a registrarsi come orchestratore

- id: T071
- title: Le sessioni che orchestrano vengono invitate a registrarsi come orchestratore
- category: engine
- priority: P2
- priority-reason: L'orchestratore di ai-coding-tools ha lavorato per giorni senza registrazione; il ruolo risultava missing
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-144411-orchestrating-sessions-are-never-told-to/note.md
- paths: -
- handoff: Read tasks/engine/T071-le-sessioni-che-orchestrano-vengono-invitate-a-reg.md, do the open steps, run the Verification, update the task and the registry.
- verifier: ai-coding-tools-87
- verify-by: ai-coding-tools
- short: Invito a registrarsi

## Goal

On 2026-10-27 the owner asked whether I (an interactive Claude session orchestrating ai-coding-tools for days) was registered: 'ai-orch orchestrator status' said role missing. Nothing in the orchestration-workflow / task-pipeline skills, the managed AGENTS.md block or the handoff prompt tells an orchestrating session to 'sessions register --role orchestrator' and heartbeat. Proposal: (1) the managed AGENTS.md block and the orchestration skill state it; (2) task-changing commands run by an unregistered session in a workspace whose role is missing print a one-line hint; (3) the UI shows 'no orchestrator' prominently.

## Steps

- [x] Blocco gestito di AGENTS.md e skill orchestration-workflow: registrarsi con sessions register --role orchestrator e mandare heartbeat
- [x] Comandi che modificano i task, lanciati in un workspace con ruolo missing, stampano un suggerimento di una riga
- [x] Le sessioni interattive (Claude Code) non mandano heartbeat da sole: l'invito spiega come mandarlo a ogni turno o a ogni controllo periodico, e lo stato "stale" di un titolare interattivo non va letto come assente (d4science-kb-3d 2026-10-27: gen 3 interattiva già stale dopo un'ora)

## Verification

- Test: ruolo missing -> il suggerimento compare; registrato -> nessun suggerimento

## Log (newest first)

- 2026-10-28, ai-coding-tools-87: state `verified` -> `done`
- 2026-10-28, ai-coding-tools-87: state `delivered` -> `verified` — Verificato dal vivo su copie: avviso presente senza orchestratore, assente con orchestratore nel workspace che contiene il progetto; due difetti corretti (lettura senza effetti collaterali, workspace padre); suite 617 verdi
