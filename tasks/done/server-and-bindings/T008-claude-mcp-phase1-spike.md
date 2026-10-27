# T008 Spike empirico di Fase 1 per `claude-mcp` (Opzione A `--bg` vs Opzione B `-p` scollegato)

- id: T008
- title: Spike empirico di Fase 1 per claude-mcp (Opzione A --bg vs Opzione B -p scollegato)
- category: server-and-bindings
- priority: P1
- priority-reason: Sblocca l'implementazione di claude-mcp come secondo binding Executor (SPEC.md e 01-claude-mcp-server/plan.md pronti)
- next-up: no
- state: done
- executor: claude
- depends-on: -
- decider: -
- sources: ../claude-mcp/SPEC.md (§3, §5), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../claude-mcp/
- handoff: Leggere tasks/server-and-bindings/T008-claude-mcp-phase1-spike.md e ../claude-mcp/SPEC.md, eseguire lo spike di Fase 1, registrare i risultati e aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Spike claude-mcp

## Goal

Eseguire lo spike empirico di Fase 1 definito in `../claude-mcp/SPEC.md` §5 per confrontare l'Opzione A (`claude "<task>" --bg --session-id <uuid>`) con l'Opzione B (`claude -p "<task>" --output-format json --session-id <uuid>` scollegato) sul comportamento reale della CLI, sul controllo di PID e annullamento e sulla lettura in coda della trascrizione JSONL.

## Steps

1. In una directory di scratch, testare l'Opzione A e l'Opzione B con la CLI `claude` su questa macchina.
2. Registrare gli output JSON esatti, il percorso e la struttura della trascrizione sotto `~/.claude/projects/` e il comportamento di annullamento in `../claude-mcp/`.
3. Fissare l'architettura di invio scelta in `../claude-mcp/SPEC.md` così da poter procedere con la Fase 2 (server MCP minimale).

## Verification

- Report dello spike scritto in `../claude-mcp/` con gli output reali dei comandi e la decisione architetturale fissata in `../claude-mcp/SPEC.md`.
