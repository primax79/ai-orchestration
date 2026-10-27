# 01 - Consolidare le skill di orchestrazione e dei task in `ai-orchestration`

- **Short:** Consolidare in ai-orchestration

> **Goal:** Rendere `ai-orchestration` il singolo repository autonomo per tutte le skill di definizione dei task e di orchestrazione, i template e i binding, lasciando `kilo-mcp` e `claude-mcp` come puri repository di server MCP standalone.

## Tasks

### 01.1 - Rinominare `ai-architect-executor` → `ai-orchestration` nei manifest del repository, negli script e nella documentazione
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** Rinomina repository
- **Focus files:** `.claude-plugin/marketplace.json`, `.kilo/marketplace.json`, `marketplace-skills.json`, `README.md`, `AGENTS.md`, `scripts/generate_skill_indices.py`, `plugins/*/.claude-plugin/plugin.json`, `plugins/*/skills/*/SKILL.md`
- **Steps:**
  1. Aggiornare tutti gli URL del repository, i nomi del marketplace e i riferimenti testuali da `ai-architect-executor` ad `ai-orchestration` in `README.md`, `AGENTS.md`, `.claude-plugin/marketplace.json`, `.kilo/marketplace.json` e `plugins/`.
  2. In `plugins/shared/skills/interactive-role-setup/SKILL.md`, aggiornare il riferimento al percorso di configurazione in `~/.config/ai-orchestration/orchestration.toml` (annotando il fallback retrocompatibile a `~/.config/ai-architect-executor/roles.toml`).
  3. Eseguire `python3 scripts/regenerate_generic_skills.py` e `python3 scripts/generate_skill_indices.py`.
- **Verification:**
  - `python3 scripts/generate_skill_indices.py` termina con codice 0 (incluso `validate_roles.py`).
  - `grep -rn "primax79/ai-architect-executor" README.md .claude-plugin/ .kilo/ plugins/` restituisce 0 occorrenze (solo gli storici `STATUS.md` e `docs/` mantengono le menzioni storiche).
- **Commit:** Singolo commit limitato a `01.1`.

### 01.2 - Consolidare `macroplan-authoring` in `ai-orchestration`
- **Profile:** `orchestration`
- **Status:** `done` (2026-10-15) · **Short:** Unire macroplan-authoring
- **Focus files:** `../agentic-coding-kit/plugins/common-tools/skills/macroplan-authoring/`, `plugins/architect-side/skills/`, `plugins/architect-side/skill-requirements.json`, `plugins/architect-side/dependencies.json`
- **Steps:**
  1. Copiare `macroplan-authoring` (`SKILL.md`, `references/template.md`) in `ai-orchestration/plugins/architect-side/skills/macroplan-authoring/` in modo che `architect-side` includa nativamente la stesura della pipeline dei task senza dipendere da un repository esterno.
  2. Aggiungere `"macroplan-authoring"` (`profile: "orchestration"`) a `plugins/architect-side/skill-requirements.json` e rimuovere la voce di dipendenza esterna da `plugins/architect-side/dependencies.json`.
  3. Eseguire `python3 scripts/generate_skill_indices.py`.
- **Verification:**
  - `python3 scripts/generate_skill_indices.py` termina con codice 0 e `plugins/architect-side/skills/index.json` elenca `macroplan-authoring`.
- **Commit:** Singolo commit limitato a `01.2`.

### 01.3 - Usabilità a livello di prodotto e per singola skill, documentazione e playbook per l'operatore
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15) · **Short:** Usabilità e playbook
- **Focus files:** `README.md`, `docs/00-QUICKSTART-AND-PLAYBOOK.md`, `plugins/*/skills/*/SKILL.md` (`SKILL.template.md`)
- **Steps:**
  1. Riscrivere `README.md` come punto di ingresso chiaro del prodotto: cos'è `ai-orchestration`, come funzionano i 3 livelli (Config & Bootstrap → Task Pipeline & State Machine → Architect/Executor Delegation & Cross-Verification), tabella completa di plugin/skill/script e istruzioni di installazione per Claude Code, Kilo Code e AI Swissknife.
  2. Scrivere `docs/00-QUICKSTART-AND-PLAYBOOK.md` coprendo ricette operative end-to-end con comandi e prompt pronti per il copia-incolla:
     - **Playbook 1:** Primo setup globale (`orchestration.toml` — configurazione di tool, MCP e modelli per-tool in base al profilo di attività).
     - **Playbook 2:** Bootstrap di un progetto nuovo o esistente (`init-project` + generazione di `AGENTS.md` + scaffolding di `tasks/`).
     - **Playbook 3:** Definizione del lavoro (quando usare una singola delega inline rispetto a un Task Emergente `T###` o a una Spec + Iniziativa completa `NN-<slug>`).
     - **Playbook 4:** Esecuzione del ciclo Architect/Executor (`agent_manager`/`task` nativo di Kilo rispetto a MCP `kilo-mcp`/`claude-mcp` o a un worktree git manuale).
     - **Playbook 5:** Esecuzione della verifica incrociata opzionale tra agenti (`self`, `cross-agent`, `panel` cieco/informato, `owner`) e chiusura dei task (`delivered → verified → done`).
  3. Standardizzare l'inizio di ogni `SKILL.md` / `SKILL.template.md` affinché ciascuna skill si apra con un **riquadro di riferimento rapido (Quick Reference)** facilmente consultabile (*Role / Audience*, *When to use*, *Inputs / Config*, *Companion Scripts / Commands*, *Outputs*).
- **Verification:**
  - Ogni link in `README.md` e `docs/00-QUICKSTART-AND-PLAYBOOK.md` si risolve correttamente; `python3 scripts/generate_skill_indices.py` termina con codice 0.
- **Commit:** Singolo commit limitato a `01.3`.
