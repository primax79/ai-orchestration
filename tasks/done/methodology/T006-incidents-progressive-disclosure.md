# T006 Estrarre le analisi degli incidenti in `references/incidents.md` (divulgazione progressiva)

- id: T006
- title: Estrarre le analisi degli incidenti in references/incidents.md (divulgazione progressiva)
- category: methodology
- priority: P3
- priority-reason: Riduce l'impronta in token all'attivazione della skill senza modificare il comportamento operativo
- next-up: no
- state: done
- executor: self
- depends-on: T003
- decider: -
- sources: ../architect-executor-consolidated-review.md (§1.4, Tier 3), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/, ../kilo-mcp/bindings/orchestration-methodology.json
- handoff: Leggere tasks/methodology/T006-incidents-progressive-disclosure.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Estrazione analisi incidenti

## Goal

Mantenere regole imperative concise in `orchestration-methodology/SKILL.template.md` spostando i racconti articolati degli incidenti reali e gli esempi specifici di dominio (annotazioni JPA, file `.ts`) in `references/incidents.md`.

## Steps

1. Misurare il conteggio iniziale di byte/token di `orchestration-methodology/SKILL.md` e `kilo-mcp-orchestrator/SKILL.md`.
2. Creare `references/incidents.md` sotto `orchestration-methodology` (e replicarlo o collegarlo in modo pulito per `kilo-mcp-orchestrator`), mantenendo regole imperative di 1-2 righe in `SKILL.template.md`.
3. Rigenerare le skill generiche e associate e registrare la riduzione di token prima/dopo.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` termina con codice 0 e ogni regola operativa rimane presente in `SKILL.md`.
