# T078 Smistare le lezioni di ricerca_auto del 2026-10-17 contro lo stato attuale

- id: T078
- title: Smistare le lezioni di ricerca_auto del 2026-10-17 contro lo stato attuale
- category: methodology
- priority: P2
- priority-reason: Osservazioni con evidenze su kilo-mcp, skill e validazione rimaste 10 giorni nell'inbox; alcune già risolte nel frattempo
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/to-analyze/2026-10-17-ricerca-auto-lessons-for-orchestration.md (sessione architetto di ricerca_auto)
- paths: kilo-mcp/server.py, tasks/specs/executor-housekeeping-and-completion.md
- handoff: Read tasks/methodology/T078-smistare-le-lezioni-di-ricerca-auto-del-2026-10-17.md, do the open steps, run the Verification, update the task and the registry.
- verifier: ai-coding-tools-d8
- short: Lezioni ricerca_auto

## Goal

Ogni richiesta della nota (sezioni A-I) è confrontata con lo stato attuale del codice (kilo-mcp, ai-orchestration, skill): già risolta, in parte o no, con file e commit; per ciò che resta esistono task nei registri giusti e la nota è smistata.

## Steps

- [x] Verifica nel codice per ogni richiesta A-I (23 punti analizzati: 9 done, 9 partial, 5 not done in `tasks/_reviews/2026-10-27-ricerca-auto-lessons-triage.md`)
- [x] Proposta di task per ciò che resta, per repo e priorità (6 task proposti: 3 in `kilo-mcp` e 3 in `ai-orchestration`, più rimando all'iniziativa 17)
- [ ] L'architetto crea i task e smista la nota

## Verification

- Tabella richiesta -> stato -> evidenza; task creati; nota in analyzed

## Log (newest first)

- 2026-10-27, ai-coding-tools-d8: state `verified` -> `done`
- 2026-10-27, ai-coding-tools-d8: state `delivered` -> `verified`
- 2026-10-27, orchestrator: state `in progress` -> `delivered`
- 2026-10-27, orchestrator: state `open` -> `in progress`
- 2026-10-27, kilo: analisi scritta in tasks/_reviews/2026-10-27-ricerca-auto-lessons-triage.md
