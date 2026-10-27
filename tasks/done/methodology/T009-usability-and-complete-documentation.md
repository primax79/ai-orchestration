# T009 Usabilità del prodotto e delle singole skill, playbook di avvio rapido e chiarezza delle istruzioni

- id: T009
- title: Usabilità del prodotto e delle singole skill, playbook di avvio rapido e chiarezza delle istruzioni
- category: methodology
- priority: P1
- priority-reason: Requisito dell'owner: usabilità chiara, documentazione e istruzioni operative sia per singola skill sia per l'intero prodotto di orchestrazione
- next-up: no
- state: done
- executor: kilo
- depends-on: 01.1, 01.2
- decider: -
- sources: conversation 2026-10-15 (owner explicit requirement)
- paths: README.md, docs/00-QUICKSTART-AND-PLAYBOOK.md, plugins/*/skills/*/SKILL.md, plugins/*/skills/*/SKILL.template.md
- handoff: Leggere tasks/methodology/T009-usability-and-complete-documentation.md e tasks/01-repo-consolidation/plan.md (01.3), scrivere docs/00-QUICKSTART-AND-PLAYBOOK.md, revisionare README.md e aggiungere intestazioni Quick Reference a ciascuna skill, quindi eseguire la Verification e aggiornare il registro.
- verifier: orchestrator:deep-reasoning
- short: Usabilità e avvio rapido

## Goal

Fornire documentazione end-to-end, playbook pratici e istruzioni facilmente consultabili per ogni skill, in modo che sia un operatore umano sia un agente AI possano configurare, inizializzare ed eseguire `ai-orchestration` (come prodotto complessivo e skill per skill) senza attriti.

## Steps

1. Scrivere `docs/00-QUICKSTART-AND-PLAYBOOK.md` con flussi di lavoro passo-passo che coprano esplicitamente sia la **Modalità nativa a singolo framework** (solo Kilo o solo Claude: definizione dei task, criteri di accettazione, worktree/subagent nativi paralleli, verifica con subagent alla cieca — senza necessità di MCP) sia la **Modalità MCP multi-framework** (delega attraverso `kilo-mcp` / `claude-mcp` / `codex`):
   - Configurazione globale e di progetto (`orchestration.toml` + generazione di `AGENTS.md` per configurazioni a singolo framework o multi-framework);
   - Scelta tra delega inline, Task emergente (`T###`) e Iniziativa (`NN-<slug>`);
   - Delega attraverso i canali (`agent_manager`/`task` nativi o `Agent` di Claude rispetto a MCP esterni `kilo-mcp`/`claude-mcp` o worktree CLI manuali);
   - Esecuzione della verifica indipendente opzionale (`self`, `independent-session` all'interno dello stesso framework, `cross-agent` tra framework diversi, `panel`, `owner`);
   - Risoluzione dei problemi e riferimento agli script (`orchestration_config.py`, `tasks_engine.py`, `apply_fix_to_worktree.sh`).
2. Revisionare `README.md` in modo che spieghi il prodotto unificato `ai-orchestration`, i suoi 3 plugin (`architect-side`, `executor-side`, `shared`), il ruolo esatto di ogni skill e come si collega a `kilo-mcp`, `claude-mcp` e alla futura UI.
3. Aggiungere una sezione **Quick Reference** uniforme in cima a ogni skill (`Role`, `When to use`, `Companion scripts`, `Related skills`) e rigenerare le skill generiche/associate e gli indici.

## Verification

- `python3 scripts/regenerate_generic_skills.py && python3 scripts/generate_skill_indices.py` termina con codice 0.
- Tutti i link relativi in `README.md` e `docs/00-QUICKSTART-AND-PLAYBOOK.md` si risolvono correttamente su disco.
