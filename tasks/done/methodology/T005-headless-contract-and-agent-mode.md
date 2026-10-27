# T005 Consolidamento di `headless-executor-contract` e valutazione della modalità agente di Kilo

- id: T005
- title: Consolidamento di headless-executor-contract e valutazione della modalità agente di Kilo
- category: methodology
- priority: P2
- priority-reason: Al contratto dell'Executor mancano regole esplicite 1-task-1-commit e sul raggio d'impatto nei worktree; il canale di consegna tramite skills_to_load richiede verifica
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§2.3, §4.3, §4.4), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/executor-side/skills/headless-executor-contract/SKILL.template.md, ../kilo-mcp/bindings/headless-executor-contract.json
- handoff: Leggere tasks/methodology/T005-headless-contract-and-agent-mode.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: orchestrator:deep-reasoning
- short: Consolidamento contratto executor

## Goal

Aggiungere le regole mancanti sull'ambito del commit, sul raggio d'impatto dell'isolamento, sullo scheletro esatto del `Final Report` e sui comandi di verifica riproducibili a `headless-executor-contract`, e controllare `metrics.jsonl` / i record dei task per decidere se sia giustificata una definizione dedicata di agente Kilo `headless-executor`.

## Steps

1. Aggiornare `../ai-architect-executor/plugins/executor-side/skills/headless-executor-contract/SKILL.template.md` e `../kilo-mcp/bindings/headless-executor-contract.json`:
   - Aggiungere la regola esplicita: effettuare il commit a fine task, limitato strettamente alle modifiche di questo task ("un task, un commit").
   - Aggiungere la regola esplicita sul raggio d'impatto dell'isolamento: non uscire mai da `working_directory`, non toccare mai i worktree fratelli né il checkout principale.
   - Includere lo scheletro Markdown esatto previsto per il `Final Report` (`Outcome`, `Files changed`, `Verification` con comando e output esatti, `Issues`).
2. Ispezionare `KILO_MCP_DATA_DIR` (`metrics.jsonl` / record dei task) per verificare se `skills_to_load` viene popolato nelle deleghe reali e decidere in merito alla modalità agente `headless-executor` (§4.4) e alla guida di scrittura delle skill per Executor (§4.3).
3. Rigenerare le skill generiche e associate e gli indici.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` termina con codice 0.
