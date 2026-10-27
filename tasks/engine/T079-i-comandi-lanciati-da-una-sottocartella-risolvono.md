# T079 I comandi lanciati da una sottocartella risolvono il workspace che la contiene

- id: T079
- title: I comandi lanciati da una sottocartella risolvono il workspace che la contiene
- category: engine
- priority: P2
- priority-reason: Da una sottocartella config show, sessions role e orchestrator status vedono un progetto inesistente e un ruolo mancante (d4science_kb, 2026-10-27)
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: d4science-kb-3d 2026-10-27, validazione di T072: da ~/works/d4science_kb/iam ogni gruppo prende iam come progetto
- paths: scripts/orchestration_sessions.py, scripts/orchestration_orchestrator.py, plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py
- handoff: Read tasks/engine/T079-i-comandi-lanciati-da-una-sottocartella-risolvono.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: d4science_kb
- short: Workspace da sottocartella

## Goal

Quando --workspace manca, config, sessions, orchestrator (e gli altri gruppi che usano la cartella corrente) risalgono dalla cartella corrente al workspace che la contiene (registro dei workspace, poi .ai-orchestration*, tasks/ o radice git) invece di usare la sottocartella; un messaggio dice quale workspace è stato scelto.

## Steps

- [ ] Una funzione comune di risoluzione del workspace dalla cartella corrente, usata da tutti i gruppi
- [ ] Test: da una sottocartella i tre comandi vedono il workspace giusto

- [ ] Test anche per T072: l'anteprima di reassign con config invariata non mostra diff (nessuna intestazione da controllare): caso coperto

## Verification

- Da ~/works/d4science_kb/iam: config show, sessions role, orchestrator status mostrano d4science_kb
