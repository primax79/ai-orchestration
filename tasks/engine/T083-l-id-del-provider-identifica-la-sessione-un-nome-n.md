# T083 L'id del provider identifica la sessione: un nome nuovo rinomina il record invece di crearne un altro

- id: T083
- title: L'id del provider identifica la sessione: un nome nuovo rinomina il record invece di crearne un altro
- category: engine
- priority: P3
- priority-reason: Dopo reassign due record condividono lo stesso id di provider (d4science_kb, validazione di T070); stesso caso del cambio di nome di ai-coding-tools-c1 -> d8
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: d4science-kb-3d 2026-10-27, validazione di T070
- paths: scripts/orchestration_sessions.py, scripts/orchestration_orchestrator.py
- handoff: Read tasks/engine/T083-l-id-del-provider-identifica-la-sessione-un-nome-n.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: d4science_kb
- short: Rinomina sessione per provider

## Goal

In sessions register e orchestrator reassign, se l'id del provider corrisponde a un record esistente, quel record viene riusato e rinominato con il nuovo session-id (storia del nome conservata), invece di creare un record nuovo e ritirare il vecchio; nessun duplicato di provider id tra record attivi o ritirati della stessa generazione.

## Steps

- [ ] Implementazione e test (rinomina con stesso provider; nessun duplicato)

## Verification

- Test: record con provider X, reassign con session-id diverso e provider X -> un solo record, rinominato, generazione +1
