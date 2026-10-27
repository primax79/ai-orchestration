# T007 Tool strutturato per il gate di verifica in `kilo-mcp`

- id: T007
- title: Tool strutturato per il gate di verifica in kilo-mcp
- category: server-and-bindings
- priority: P2
- priority-reason: Riduce il consumo di contesto dell'Architect nella Fase 5 restituendo verdetti strutturati pass/fail invece dei dump completi dei log
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§3.2), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../kilo-mcp/server.py, ../kilo-mcp/test_server.py
- handoff: Leggere tasks/server-and-bindings/T007-verification-gate-tool.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Tool gate di verifica

## Goal

Aggiungere a `kilo-mcp/server.py` una funzionalità di gate di verifica che esegua i comandi di controllo del progetto (lint, test, build) in una `working_directory`/worktree di destinazione e restituisca un verdetto strutturato compatto (pass/fail per comando + solo la coda dell'output in caso di fallimento).

## Steps

1. Progettare se realizzarlo come `@mcp.tool() kilo_verify_worktree` dedicato o come modalità di controllo strutturata, supportando comandi espliciti o controlli di progetto configurati via TOML.
2. Implementare in `../kilo-mcp/server.py` con protezione da timeout e troncamento dell'output per i controlli superati.
3. Aggiungere unit test in `../kilo-mcp/test_server.py` e documentare in `../kilo-mcp/README.md`.

## Verification

- `../kilo-mcp/.venv/bin/pytest ../kilo-mcp/test_server.py` passa.
