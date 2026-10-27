# 05 - CLI standalone (`ai-orch`), installatore da zero e piano di controllo per l'estensione

- **Short:** CLI installer control plane

> **Derived from:** [`../specs/orchestration-extension-spec.md`](../../specs/orchestration-extension-spec.md) e [`../../docs/03-task-model-and-ui-architecture.md`](../../../docs/03-task-model-and-ui-architecture.md)

## Tasks (One Task = One Commit)

### 05.1 - Punto di ingresso unificato della CLI `bin/ai-orch` (`config`, `tasks`, `render-agents-md`, `describe`)
- **Status:** `done` (2026-10-15) · **Short:** CLI ai-orch unificata
- **Goal:** Fornire un unico wrapper CLI `bin/ai-orch` sopra `orchestration_config.py` e `tasks_engine.py` con output `--json` e `describe`.

### 05.2 - Installatore da zero e Doctor dell'ambiente (`scripts/orchestration_env.py`, `install.sh`, `ai-orch env`)
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15) · **Short:** Installatore e Doctor
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`, `install.sh`, `bin/ai-orch`
- **Goal:** Fornire uno script privo di dipendenze esterne (`scripts/orchestration_env.py`, esposto come `./bin/ai-orch env <status|install|register-mcp>` e `./install.sh`) per gli utenti che installano da zero e per i Macro-Task 2 e 3 dell'estensione:
  1. **Download / Clone / Update** di `ai-orchestration` e `kilo-mcp` (da GitHub in `~/.ai-orchestration/repos/` oppure usando i checkout locali quando presenti);
  2. **Installazione di skill e agenti** in Kilo Code (`~/.kilo/skills` o `<workspace>/.kilo/skills`) e Claude Code (`~/.claude/skills` o `<workspace>/.claude/skills`), supportando sia le skill generiche Single-Framework (`architect-side`, `executor-side`, `shared`) sia le skill vincolate a MCP (`kilo-mcp`), e rilevando conflitti tra duplicati generici e vincolati;
  3. **Provisioning e registrazione dei server MCP** (`kilo-mcp`, `claude-mcp`): creare/aggiornare il `.venv` Python, installare il pacchetto e registrare il server MCP in Claude (`~/.claude.json` / `.mcp.json`) e Kilo (`~/.config/kilo/kilo.json` / `.kilo/kilo.jsonc`);
  4. **Verifica dello stato dell'ambiente (`status` / `doctor`)**: riportare lo stato JSON/leggibile dei binari CLI (`kilo`, `claude`, `codex`), delle skill installate (con rilevamento della deriva tramite hash del contenuto: `up-to-date`, `modified-locally`, `missing`, `conflict`), dei server MCP registrati e di `orchestration.toml`.
- **Verification:** `pytest scripts/test_orchestration_env.py` (3 passati) e `./bin/ai-orch env status --json` passano.

### 05.3 - Backend dell'estensione / Web UI e vista Backlog Manager (Macro-Task 1)
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** Backend Backlog Manager
- **Repo:** `ai-orchestration-ui/`
- **Goal:** Costruire la UI del Backlog Manager (panoramica dell'avanzamento, coda `Next up`, bacheca Kanban per stato, albero Iniziativa/Categoria ed editor di dettaglio Task/Spec per priorità, assegnatario/esecutore, profilo, modalità di verifica e transizioni di stato) supportata da `ai-orch tasks --json`.
- **Verification:** Gli unit test in `backend/test_server.py` passano e Vite compila `frontend/dist/` senza errori.

### 05.4 - Installatore dell'ambiente, Doctor e configuratore dell'orchestratore per estensione / Web UI (Macro-Task 2, 3, 4)
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** UI installer e configuratore
- **Repo:** `ai-orchestration-ui/`
- **Goal:** Costruire le viste UI per:
  - **Macro-Task 2 e 3 (Installatore di skill e MCP + Doctor dell'ambiente):** supportati da `ai-orch env status --json` e `ai-orch env install --json`;
  - **Macro-Task 4 (Configuratore dell'orchestratore di progetto):** editor visuale per `orchestration.toml` globale e di progetto (framework attivi, orchestratore primario, matrice dei modelli per-tool, policy di verifica, regole di isolamento) + anteprima e applicazione con un clic di `AGENTS.md` (`ai-orch render-agents-md --apply`).
- **Verification:** Il backend Starlette serve il bundle statico su `/`, tutte le rotte REST e WebSocket sono testate, pronto per l'incorporamento nel pannello Webview di VS Code tramite `vscode.postMessage` in `frontend/src/api.ts`.
