# T004 Rielaborare `conflict-resolver` per il ruolo Architect e i design incompatibili

- id: T004
- title: Rielaborare conflict-resolver per il ruolo Architect e i design incompatibili
- category: methodology
- priority: P2
- priority-reason: Lo stub attuale si rivolge al ruolo sbagliato e istruisce l'agente a preservare entrambi i lati anche quando i design sono incompatibili
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§2.5), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/architect-side/skills/conflict-resolver/SKILL.template.md, ../kilo-mcp/bindings/conflict-resolver.json
- handoff: Leggere tasks/methodology/T004-conflict-resolver-rework.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Rielaborazione conflict-resolver

## Goal

Riscrivere `conflict-resolver` (`SKILL.template.md` + binding `kilo-mcp`) in modo che si rivolga all'Architect al momento del merge nella Fase 6, separi i conflitti meccanici da quelli di design incompatibili e richieda l'esecuzione delle suite di test di entrambe le funzionalità oltre alla registrazione dei conflitti ricorrenti nella telemetria di decomposizione.

## Steps

1. Aggiornare `../ai-architect-executor/plugins/architect-side/skills/conflict-resolver/SKILL.template.md` e `../kilo-mcp/bindings/conflict-resolver.json`:
   - Riorientare il testo verso l'Architect che esegue l'integrazione di Fase 6.
   - Aggiungere la biforcazione principale: **conflitto meccanico** (import, barrel export, registrazioni adiacenti → combinare entrambi) rispetto a **conflitto di design/firma incompatibile** (fermarsi, scegliere un design, rimandare l'altro task alla sua sessione o chiedere all'utente).
   - Richiedere l'esecuzione delle suite di test di **entrambe** le funzionalità coinvolte più la build dell'applicazione consumatrice dopo la risoluzione.
   - Istruire a registrare i conflitti non banali come telemetria di decomposizione (`kilo_log_issue`).
2. Rigenerare le skill generiche e associate e gli indici.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` termina con codice 0.
