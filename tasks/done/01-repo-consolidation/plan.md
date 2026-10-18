# 01 - Consolidate Orchestration & Task Skills into `ai-orchestration`

- **Short:** Consolidate into ai-orchestration

> **Goal:** Make `ai-orchestration` the single, self-contained repository for all task-definition and orchestration skills, templates, and bindings, leaving `kilo-mcp` and `claude-mcp` as pure standalone MCP server repos.

## Tasks

### 01.1 - Rename `ai-architect-executor` → `ai-orchestration` across Repo Manifests, Scripts & Docs
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** Repo rename
- **Focus files:** `.claude-plugin/marketplace.json`, `.kilo/marketplace.json`, `marketplace-skills.json`, `README.md`, `AGENTS.md`, `scripts/generate_skill_indices.py`, `plugins/*/.claude-plugin/plugin.json`, `plugins/*/skills/*/SKILL.md`
- **Steps:**
  1. Update all repository URLs, marketplace names, and prose references from `ai-architect-executor` to `ai-orchestration` across `README.md`, `AGENTS.md`, `.claude-plugin/marketplace.json`, `.kilo/marketplace.json`, and `plugins/`.
  2. In `plugins/shared/skills/interactive-role-setup/SKILL.md`, update the config path reference to `~/.config/ai-orchestration/orchestration.toml` (noting backward-compatible fallback to `~/.config/ai-architect-executor/roles.toml`).
  3. Run `python3 scripts/regenerate_generic_skills.py` and `python3 scripts/generate_skill_indices.py`.
- **Verification:**
  - `python3 scripts/generate_skill_indices.py` exits 0 (including `validate_roles.py`).
  - `grep -rn "primax79/ai-architect-executor" README.md .claude-plugin/ .kilo/ plugins/` returns 0 hits (only historical `STATUS.md` and `docs/` keep historical mentions).
- **Commit:** Single commit scoped to `01.1`.

### 01.2 - Consolidate `macroplan-authoring` into `ai-orchestration`
- **Profile:** `orchestration`
- **Status:** `done` (2026-10-15) · **Short:** Merge macroplan-authoring
- **Focus files:** `../agentic-coding-kit/plugins/common-tools/skills/macroplan-authoring/`, `plugins/architect-side/skills/`, `plugins/architect-side/skill-requirements.json`, `plugins/architect-side/dependencies.json`
- **Steps:**
  1. Copy `macroplan-authoring` (`SKILL.md`, `references/template.md`) into `ai-orchestration/plugins/architect-side/skills/macroplan-authoring/` so `architect-side` includes task-pipeline authoring out of the box without an external repo dependency.
  2. Add `"macroplan-authoring"` (`profile: "orchestration"`) to `plugins/architect-side/skill-requirements.json` and remove the external dependency entry from `plugins/architect-side/dependencies.json`.
  3. Run `python3 scripts/generate_skill_indices.py`.
- **Verification:**
  - `python3 scripts/generate_skill_indices.py` exits 0 and `plugins/architect-side/skills/index.json` lists `macroplan-authoring`.
- **Commit:** Single commit scoped to `01.2`.

### 01.3 - Product-Level & Per-Skill Usability, Documentation, and Operator Playbook
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15) · **Short:** Usability and playbook
- **Focus files:** `README.md`, `docs/00-QUICKSTART-AND-PLAYBOOK.md`, `plugins/*/skills/*/SKILL.md` (`SKILL.template.md`)
- **Steps:**
  1. Rewrite `README.md` as a crystal-clear product entry point: what `ai-orchestration` is, how the 3 layers work (Config & Bootstrap → Task Pipeline & State Machine → Architect/Executor Delegation & Cross-Verification), complete table of plugins/skills/scripts, and installation instructions for Claude Code, Kilo Code, and AI Swissknife.
  2. Write `docs/00-QUICKSTART-AND-PLAYBOOK.md` covering end-to-end operational recipes with copy-pasteable commands and prompts:
     - **Playbook 1:** First-time global setup (`orchestration.toml` — configuring tools, MCPs, and per-tool models by activity profile).
     - **Playbook 2:** Bootstrapping a new or existing project (`init-project` + generating `AGENTS.md` + scaffolding `tasks/`).
     - **Playbook 3:** Defining work (when to use a single inline delegation vs. an Emergent Task `T###` vs. a full Spec + Initiative `NN-<slug>`).
     - **Playbook 4:** Running the Architect/Executor loop (native Kilo `agent_manager`/`task` vs. MCP `kilo-mcp`/`claude-mcp` vs. manual git worktree).
     - **Playbook 5:** Running Optional Cross-Agent Verification (`self`, `cross-agent`, `panel` blind/primed, `owner`) and closing tasks (`delivered → verified → done`).
  3. Standardize the top of every `SKILL.md` / `SKILL.template.md` so each skill starts with a scannable **Quick Reference box** (*Role / Audience*, *When to use*, *Inputs / Config*, *Companion Scripts / Commands*, *Outputs*).
- **Verification:**
  - Every link in `README.md` and `docs/00-QUICKSTART-AND-PLAYBOOK.md` resolves; `python3 scripts/generate_skill_indices.py` exits 0.
- **Commit:** Single commit scoped to `01.3`.
