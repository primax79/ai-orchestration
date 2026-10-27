# T078 Smistare le lezioni di ricerca_auto del 2026-10-17 contro lo stato attuale

- id: T078
- title: Smistare le lezioni di ricerca_auto del 2026-10-17 contro lo stato attuale
- category: methodology
- priority: P2
- priority-reason: Osservazioni con evidenze su kilo-mcp, skill e validazione rimaste 10 giorni nell'inbox; alcune già risolte nel frattempo
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/to-analyze/2026-10-17-ricerca-auto-lessons-for-orchestration.md (sessione architetto di ricerca_auto)
- paths: kilo-mcp/server.py, tasks/specs/executor-housekeeping-and-completion.md
- handoff: Read tasks/methodology/T078-smistare-le-lezioni-di-ricerca-auto-del-2026-10-17.md, do the open steps, run the Verification, update the task and the registry.
- short: Lezioni ricerca_auto

## Goal

Ogni richiesta della nota (sezioni A-I) è confrontata con lo stato attuale del codice (kilo-mcp, ai-orchestration, skill): già risolta, in parte o no, con file e commit; per ciò che resta esistono task nei registri giusti e la nota è smistata.

## Steps

- [ ] Verifica nel codice per ogni richiesta A-I
- [ ] Proposta di task per ciò che resta, per repo e priorità
- [ ] L'architetto crea i task e smista la nota

## Verification

- Tabella richiesta -> stato -> evidenza; task creati; nota in analyzed
