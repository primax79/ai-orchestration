# T021 Precedenza tra orchestration-workflow e kilo-mcp-orchestrator; correzione del disallineamento del template di binding

- id: T021
- title: Precedenza tra orchestration-workflow e kilo-mcp-orchestrator; correzione del disallineamento del template di binding
- category: methodology
- priority: P2
- priority-reason: Risposta aperta dell'owner a Q003; T018 mostra che la skill associata ha perso le modalità di verifica, la tabella decisionale e la tabella degli stati
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: plugins/architect-side/skills/orchestration-workflow/, ../kilo-mcp/bindings/orchestration-workflow.json, ../kilo-mcp/plugins/architect-side/skills/kilo-mcp-orchestrator/
- handoff: Leggere tasks/methodology/T021-precedence-between-orchestration-workflow-and-kilo.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- short: Drift template di binding

## Goal

Implementare le sezioni 4 e 5 di tasks/env-doctor/notes/T018-precedence-analysis.md: testo di precedenza reciproca in entrambe le skill, descrizioni non in competizione, mantenimento delle modalità di verifica / tabella decisionale post-verifica / tabella degli stati / controllo dello scaffolding nella skill associata (template non sovrascritto), cadenza dell'health-check, nota su attesa bloccante rispetto a monitoraggio scollegato e regola sullo stato di invio (in progress prima dell'invio, delivered al Final Report) nel binding affinché la rigenerazione la preservi.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
