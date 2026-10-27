# T070 orchestrator reassign lega il ruolo a una sessione interattiva esistente

- id: T070
- title: orchestrator reassign lega il ruolo a una sessione interattiva esistente
- category: engine
- priority: P2
- priority-reason: Oggi crea una sessione headless fantasma e due salti di generazione (d4science_kb)
- next-up: no
- state: in progress
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-144357-orchestrator-reassign-cannot-hand-the-ro/note.md
- paths: ai-orch orchestrator reassign; ai-orch sessions register; UC028
- handoff: Read tasks/engine/T070-orchestrator-reassign-lega-il-ruolo-a-una-sessione.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: d4science_kb
- short: Reassign su sessione attuale

## Goal

What (2026-10-27, workspace ~/works/d4science_kb): the owner declared the current interactive Claude Code session the orchestrator. Holder was gen 1, kilo, kind=interactive, status stale, turns 0.

## Steps

- [ ] reassign --kind interactive --provider-session-id <id> (o --bind-current) lega il ruolo alla sessione indicata con un solo salto di generazione, senza creare sessioni fantasma

## Verification

- Test: titolare gen 1 interattivo stale; reassign --bind-current -> gen 2 con la sessione indicata, nessuna sessione headless creata
