# T003 Punto decisionale esplicito della Fase 5 e chiusura del ciclo di vita dei worktree

- id: T003
- title: Punto decisionale esplicito della Fase 5 e chiusura del ciclo di vita dei worktree
- category: methodology
- priority: P1
- priority-reason: Agli orchestratori interattivi mancano i criteri espliciti merge/fix-inline/bounce/ask e lasciano worktree orfani in caso di annullamento
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§2.2, §2.7), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md, ../kilo-mcp/bindings/orchestration-methodology.json, ../kilo-mcp/plugins/architect-side/agents/mcp-orchestrator-agent.md
- handoff: Leggere tasks/methodology/T003-phase5-decision-and-worktree-cleanup.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Chiusura Fase 5

## Goal

Promuovere i criteri decisionali espliciti post-verifica (`merge` / `fix inline` / `bounce via continue_session_id` / `stop and ask user`) nella Fase 5 di `orchestration-methodology`, definire la pulizia dei worktree per ogni stato terminale (inclusi `cancelled` e `discarded`) e limitare i controlli modello/autenticazione della Fase 1 a una volta per sessione o dopo un errore.

## Steps

1. Modificare `../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md` e `../kilo-mcp/bindings/orchestration-methodology.json`:
   - Limitare il controllo motore/modello/autenticazione della Fase 1 a una volta per sessione o dopo un errore di invio.
   - Aggiungere la tabella decisionale esplicita a 4 vie alla fine della Fase 5.
   - Nella Fase 4 e nella Fase 6, specificare la pulizia di worktree e branch (`git worktree remove` + gestione del branch) per le run annullate e scartate, non solo per quelle unite tramite merge.
2. Rigenerare le skill generiche e associate (`regenerate_generic_skills.py`, `regenerate_bound_skills.py`) e gli indici.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` termina con codice 0.
- `python3 ../ai-architect-executor/plugins/shared/skills/interactive-role-setup/scripts/validate_roles.py --plugin-dir ../ai-architect-executor/plugins/architect-side --plugin-dir ../ai-architect-executor/plugins/executor-side --plugin-dir ../ai-architect-executor/plugins/shared` termina con codice 0.
