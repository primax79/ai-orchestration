# Installation Guide — `ai-orchestration`

This guide covers installing `ai-orchestration` (skills, configuration, and optional MCP servers) across **Kilo Code**, **Claude Code**, **Codex CLI**, and **AI Swissknife**, whether you are starting from a fresh machine or an existing workspace checkout.

---

## 1. Automated Installation (Recommended)

The repository includes `install.sh` (backed by `scripts/orchestration_env.py` / `./bin/ai-orch env`), which handles both **Single-Framework Native** setups (skills only, zero MCP) and **Multi-Framework MCP** setups (skills + `kilo-mcp` / `codex-mcp` registration).

### 1.1 From a Local Clone
```bash
git clone https://github.com/primax79/ai-orchestration.git
cd ai-orchestration

# Install skills globally for Kilo, Claude, and Codex + init ~/.config/ai-orchestration/orchestration.toml
./install.sh

# Or also clone, create .venv, and register MCP servers (kilo-mcp, codex-mcp) automatically:
./install.sh --with-mcp
```

### 1.2 One-Liner (From Scratch, No Prior Clone Required)
```bash
curl -fsSL https://raw.githubusercontent.com/primax79/ai-orchestration/main/install.sh | bash
```
When run outside a local checkout, `install.sh` automatically clones `ai-orchestration` into `~/.ai-orchestration/repos/ai-orchestration` before installing.

### 1.3 Targeted Installation Options (`./bin/ai-orch env`)
```bash
# Install only for specific assistants (e.g. only Kilo and Codex)
./bin/ai-orch env install-skills --assistants kilo codex --scope global

# Install into a single project workspace (<repo>/.kilo/skills, .claude/skills, .codex/skills)
./bin/ai-orch env install-skills --assistants all --scope project --workspace /path/to/repo

# Symlink skills to the repo checkout (edits in repo reflect immediately)
./bin/ai-orch env install-skills --assistants all --scope global --link

# Register MCP servers (kilo-mcp, claude-mcp, codex-mcp)
./bin/ai-orch env register-mcp kilo-mcp --assistants claude codex --provision-venv
./bin/ai-orch env register-mcp codex-mcp --assistants claude kilo
```

---

## 2. Manual / Native Installation per Assistant

### 2.1 Claude Code (Plugin Marketplace)
```bash
claude plugin marketplace add https://github.com/primax79/ai-orchestration.git
/plugin install architect-side
/plugin install executor-side
/plugin install shared
```

### 2.2 Kilo Code (Native Skill URLs)
Add the plugin skill URLs to your global `~/.config/kilo/kilo.json` or project `.kilo/kilo.jsonc`:
```text
https://raw.githubusercontent.com/primax79/ai-orchestration/main/plugins/architect-side/skills/
https://raw.githubusercontent.com/primax79/ai-orchestration/main/plugins/executor-side/skills/
https://raw.githubusercontent.com/primax79/ai-orchestration/main/plugins/shared/skills/
```

### 2.3 Codex CLI (`~/.codex/skills`)
```bash
./bin/ai-orch env install-skills --assistants codex --scope global
```

### 2.4 AI Swissknife (VS Code Extension / CLI)
Add `https://github.com/primax79/ai-orchestration.git` in the **AI Swissknife → Sources** view (or via `$SWK_CLI source add`), then install `architect-side`, `executor-side`, and `shared` to your target assistants and scopes.

---

## 3. Choosing Generic vs. MCP-Bound Skills (Avoiding Trigger Conflicts)

| Your Setup | Which `architect-side` / `executor-side` to Install |
| :--- | :--- |
| **Single-Framework Native** (Kilo-only, Claude-only, or Codex-only without MCP) | Install from **`ai-orchestration`** (`--repo ai-orchestration`, default). |
| **Multi-Framework driving Kilo via `kilo-mcp`** | Install `kilo-mcp`'s bound skills into the orchestrating assistant (`./bin/ai-orch env install-skills --repo kilo-mcp --assistants claude`). |

> **Important:** Do not install both generic `orchestration-workflow` (`ai-orchestration`) and bound `kilo-mcp-orchestrator` (`kilo-mcp`) into the same assistant and scope at the same time—they share the same trigger description. `./bin/ai-orch env status` automatically detects and warns you if both are present.

---

## 4. Verifying Your Installation (`ai-orch env status`)

Run the environment doctor at any time to check CLI binaries (`kilo`, `claude`, `codex`), source repositories, installed skill versions/drift (`up-to-date`, `modified-or-outdated`, `unmanaged`), conflicts, and registered MCP servers:

```bash
./bin/ai-orch env status
# Or as structured JSON:
./bin/ai-orch env status --json
```
