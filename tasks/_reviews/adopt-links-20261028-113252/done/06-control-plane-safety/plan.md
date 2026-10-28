# 06 - Sicurezza del piano di controllo (Doctor, indice, backend UI, bridge VS Code)

- **Short:** Sicurezza control-plane

> **Derived from:** [`../specs/control-plane-safety.md`](../../specs/control-plane-safety.md). Leggere prima la specifica; questo piano non la ripete. Gli id dei rilievi (E*, I*, U*, V*) fanno riferimento al suo §1.

E1 ed E2 (path traversal in `remove-skill`, sovrascrittura integrale di file di configurazione MCP non analizzabili) sono stati corretti inline in `ai-orchestration@2ca3377`, con test di regressione.

## Ondate

| Ondata | Task (paralleli, file disgiunti) |
| --- | --- |
| 1 | 06.1 (`tasks_engine.py`), 06.2 (`orchestration_env.py`), 06.5 (backend UI) |
| 2 | 06.3 (`orchestration_env.py`, dopo 06.2), 06.6 (`orchestration_config.py`) |
| 3 | 06.4 (`orchestration_env.py`, dopo 06.3), 06.7 (backend UI, dopo 06.1, 06.2, 06.5, 06.6) |
| 4 | 06.8 (frontend, dopo 06.7) |
| 5 | 06.9 (VS Code, dopo 06.8) |

## Tasks (One Task = One Commit)

## Modifiche dopo la revisione 2 (2026-10-16)

La specifica ora si apre con il §0 "Amendments after review 2" (A1–A12). Da esso discendono queste modifiche ai task:

- **06.2** copre anche A2 (hash del contenuto nel piano, applicazione sotto `env.lock`), A3 (file degli agenti, `fetch-repos`, `--provision-venv`) e A4 (ricevute). È stato avviato prima della revisione; il delta viene inviato come follow-up nella stessa sessione Kilo.
- **06.3** segue A5 (abilitazione dalle impostazioni; elenco di `{name, origin, scope, path, enabled}`).
- **06.4** segue A1 e A6:
  - `kilo.json` di Kilo è una vera configurazione unita, non un file spurio (stray);
  - Codex è solo globale tramite `codex mcp add`;
  - il fallback su file di Claude tiene conto dell'ambito (scope-aware).
- **06.5** copre anche A8 (pulizia del gruppo di processi al timeout). È stato avviato prima della revisione; il delta segue nella stessa sessione.
- **06.6** copre anche A10 per `render-agents-md` (già nell'ambito). La parte `set-routing`/`set-profile` `--diff`/`--expect-hash` passa a 07.1.
- **06.7** ora dipende da 06.3, 06.4 e **06.10**. Il backend mappa i rifiuti per hash obsoleto a 409.
- **06.8** aggiunge A12 (rendering Markdown con escape, controllo CSP, fixture XSS) alla propria verifica.
- **06.9** segue A11: `dist-webview/` committato, script di sincronizzazione solo per lo sviluppo, compilazione indipendente dal repository fratello.

## Ordine delle corsie UI (file condivisi tra 06, 07, 08)

I file del backend, del frontend e di `vscode-ai-orchestration` sono condivisi dalle tre iniziative. I relativi task vengono eseguiti **in questo ordine e mai in parallelo all'interno di una corsia**:

- **Backend** (`ai-orchestration-ui/backend/*`): 06.5 → 06.7 → 07.6 → 08.3
- **Frontend** (`ai-orchestration-ui/frontend/**`): 06.8 → 08.4 → 11.3 → 10.2 → 10.5 → 07.7 → 07.8 → 09.3 → 08.6 → 09.5
- **VS Code** (`vscode-ai-orchestration/**`): 06.9 → 08.5 → 07.9 → 09.6 → 10.3

Corsie principali (core):

- **`tasks_engine.py`:** 06.1 → 06.10 → 08.1 → 09.1 → 11.1 → 11.4 → 10.1 → 10.4
- **`orchestration_env.py`:** 06.2 → 06.3 → 06.4
- **`orchestration_config.py`:** 07.1 → 06.6
- **`orchestration_runs.py`:** 07.2 → 07.3 → 07.4 → 07.10 → 11.2 → 07.11 → 07.5 → 09.4

## Closed

### 06.1 - `sync-index` senza perdita di dati con marcatori delle regioni generate (I1–I4)

- **Status:** `done` (2026-10-16) · **Short:** sync-index senza perdite · **Profile:** `deep-reasoning` · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../scripts/test_tasks_engine.py`, `.../scripts/fixtures/index-regression/` (nuovo), `tasks/00-INDEX.md` (adozione marcatori)
- **Goal:** Implementare integralmente il §2.2 della specifica:
  - marcatori, più `--adopt`;
  - unione a livello di riga preservando `Closed`/`Result` di Done;
  - righe `(missing)`;
  - riga generica per Decisions vuoto;
  - scrittura atomica, diff `--check`, `--expect-hash`.

  Eseguire poi `--adopt` sul file `tasks/00-INDEX.md` di questo repository e committare il risultato.
- **Verification:**
  - Test su fixture con una copia curata dell'indice del workspace (con nota di provenienza nel README della fixture):
    - `--adopt` seguito da `--apply` non perde alcuna riga, alcuna cella Done né alcuna riga di testo;
    - un secondo `--apply` è una no-op;
    - mancata corrispondenza di `--expect-hash` → rifiutato, file invariato;
    - un indice privo di marcatori + `--apply` → rifiutato.
  - L'intera suite di test del motore passa.
  - `./bin/ai-orch tasks sync-index --tasks-dir ./tasks --check` termina con codice 0 dopo l'adozione.

### 06.2 - Doctor: piani `--dry-run` con hash, installazione senza sovrascrittura, cestino invece di eliminazione, pulizia esplicita degli obsoleti (E4, E6, E7)

- **Status:** `done` (2026-10-16) · **Short:** Piani sicuri del Doctor · **Profile:** `deep-reasoning` · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`
- **Goal:** Implementare il §2.1 della specifica:
  - i punti "Every mutating `env` command" e "No clobbering": `--dry-run` con `plan` + `plan_hash`, `--expect-plan-hash`, `--overwrite`, `.ai-orch-trash/`;
  - il catalogo sorgente indicizzato per `(repo, plugin, name)` con lo stato `foreign`;
  - la policy di risoluzione da `[env.conflicts]`.

  Esclusa la consapevolezza dei plugin (06.3) ed esclusa la registrazione MCP (06.4).
- **Verification:**
  - Test in una home simulata:
    - installazione sopra una skill `unmanaged`, una modificata localmente e una `foreign` → rifiutata senza `--overwrite`;
    - con `--overwrite`, la vecchia copia finisce in `.ai-orch-trash/`;
    - `--dry-run` non modifica nulla su disco (confronto dell'hash dell'albero prima e dopo);
    - un `--expect-plan-hash` obsoleto → rifiutato;
    - le directory obsolete compaiono nel piano e vengono rimosse solo in fase di applicazione.
  - Dal vivo: `env install-skills --dry-run --assistants all --scope global` sulla home reale restituisce un piano e non modifica nulla (`find ~/.claude/skills ~/.kilo/skills ~/.codex/skills -newer <marker>` è vuoto).

### 06.3 - Doctor: inventario e conflitti consapevoli dei plugin (E5)

- **Status:** `done` (2026-10-17) · **Short:** Inventario con plugin · **Profile:** `deep-reasoning` · **Depends on:** 06.2 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`
- **Goal:** Implementare il §2.1 "Plugin-aware inventory" della specifica:
  - skill dei plugin Claude da `~/.claude/plugins/installed_plugins.json`;
  - skill del marketplace Kilo, se risiedono su disco (verificare prima la disposizione reale sotto `~/.kilo` / `../references/`; in caso contrario, segnalarlo nel Final Report e saltare);
  - un campo `origin` su ogni skill;
  - conflitti calcolati sull'unione delle origini;
  - `resolve-conflicts` che tocca solo le copie `standalone` e segnala quale plugin disabilitare per le copie da plugin.
- **Verification:**
  - Test con un `installed_plugins.json` simulato.
  - Dal vivo: `env status --json` su questa macchina elenca le copie plugin `architect-side@ai-orchestration` e `architect-side@kilo-mcp` di `orchestration-workflow` / `kilo-mcp-orchestrator` e segnala il conflitto; `resolve-conflicts --dry-run` non propone modifiche ai plugin.

### 06.4 - Doctor: registrazione e stato MCP tramite i veri file di configurazione (E3)

- **Status:** `done` (2026-10-17) · **Short:** Stato registrazione MCP · **Profile:** `deep-reasoning` · **Depends on:** 06.3 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_env.py`, `scripts/test_orchestration_env.py`
- **Goal:** Implementare il §2.1 "MCP registration through the real configs" della specifica:
  - Claude tramite `claude mcp add`;
  - Codex tramite `codex mcp add` o modifica chirurgica di `config.toml`;
  - modifica di `kilo.jsonc` per Kilo, oppure frammento da incollare;
  - lettura dello stato dai file reali;
  - segnalazione dei file `stray`.

  Verificare la sintassi `mcp add` di ciascuna CLI con `--help` prima di usarla.
- **Verification:**
  - Test con una home simulata ed eseguibili stub `claude`/`codex` su `PATH` che registrano il proprio argv.
  - Dal vivo, sola lettura: `env status --json` segnala `~/.codex/config.json` come `stray` ed elenca i server MCP effettivamente presenti in `~/.codex/config.toml` (`kilo-mcp`, `playwright`, `vscode-dap`).
  - Dal vivo, scrittura: solo `register-mcp --dry-run`. Nessuna registrazione reale.

### 06.5 - Backend UI: autenticazione, chiamate CLI non bloccanti, workspace fisso, watcher (U1, U4, U5, U6)

- **Status:** `done` (2026-10-16) · **Short:** Hardening backend UI · **Profile:** `bulk-execution` · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`, `start.sh`, `README.md`, `frontend/src/api.ts`, `frontend/index.html`
- **Goal:** Implementare il §2.3 della specifica:
  - "Auth" (token persistito, iniezione meta con `no-store`, controlli sull'header e sulla query WS, allowlist di Host, rimozione di CORS);
  - "Non-blocking CLI calls";
  - "Fixed workspace per process" (con rimozione di `/api/workspace/switch`);
  - "Watcher";
  - il README.

  `api.ts` legge il meta token, lo invia e ricarica una volta su 401; il suo percorso VS Code resta invariato.
- **Verification:**
  - Test:
    - `/api/*` senza il token o con uno errato → 401; un `Host` non valido → 400; WS senza il token rifiutato;
    - una CLI stub lenta non blocca una richiesta concorrente a `/api/workspace`;
    - toccare un file sotto `tasks/` trasmette `changed` entro 2 s;
    - `AI_ORCH_WORKSPACE` viene rispettato, incluso un percorso relativo passato a `start.sh`.
  - Dal vivo: eseguire prima `npm run build`. Poi avviare su una copia temporanea del workspace e aprire la UI con il server MCP Playwright: i dati vengono caricati. Una `fetch` verso l'API da un'altra origine (pagina `about:blank`) viene rifiutata.

### 06.6 - Core: `render-agents-md --diff` con precondizione sull'hash

- **Status:** `done` (2026-10-16) · **Short:** Diff di render-agents-md · **Profile:** `bulk-execution` · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py`, `.../scripts/test_orchestration_config.py`
- **Goal:** `render-agents-md --diff` restituisce `{diff, hash}` (hash dell'attuale `AGENTS.md`, oppure del vuoto quando il file manca). `--apply --expect-hash H` rifiuta in caso di mancata corrispondenza. La scrittura è atomica.
- **Verification:** Test: un diff per un blocco mancante, un blocco presente e un blocco già aggiornato; una mancata corrispondenza dell'hash viene rifiutata e il file resta invariato.

### 06.7 - Backend UI: endpoint preview/apply; le transizioni non scrivono più l'indice (U2, U3)

- **Status:** `done` (2026-10-17) · **Short:** Endpoint preview/apply · **Profile:** `bulk-execution` · **Depends on:** 06.1, 06.2, 06.5, 06.6 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Implementare il §2.3 della specifica:
  - "Transitions no longer write the index";
  - "Preview/apply endpoints" per sync-index, ogni comando `env` mutante e `render-agents-md`.
- **Verification:**
  - Test: una transizione lascia `00-INDEX.md` identico byte per byte; ogni ciclo completo preview → apply funziona; un hash obsoleto → 409.
  - Dal vivo con `curl` verso un server in esecuzione su un workspace temporaneo.

### 06.8 - Frontend: modale di conferma con anteprime, impostazioni predefinite più sicure per l'installatore, origini del Doctor, banner di errore, riconnessione WS (U3, U7, V3)

- **Status:** `done` (2026-10-17) · **Short:** Modali di conferma · **Size:** L · **Profile:** `bulk-execution` · **Depends on:** 06.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Implementare il §2.4 della specifica; ricompilare `dist/`.
- **Verification:**
  - `npm run build` termina senza errori.
  - Dal vivo con il server MCP Playwright su un workspace temporaneo e una home simulata (override di `HOME` per il backend):
    - ogni azione mutante mostra un'anteprima e non fa nulla su Annulla;
    - un'applicazione dopo una modifica esterna mostra l'errore di piano obsoleto;
    - l'arresto del server spegne l'indicatore; il riavvio si riconnette senza ricaricare la pagina;
    - non rimane alcuna chiamata `alert`/`confirm` (`grep`).

### 06.10 - Core: lock di scrittura sui task, `--expect-task-hash`, scritture atomiche (A9)

- **Status:** `done` (2026-10-17) · **Short:** Lock scrittura task · **Profile:** `deep-reasoning` · **Depends on:** 06.1 (stesso file) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../scripts/test_tasks_engine.py`, `README.md` (nota sulla piattaforma)
- **Goal:**
  - Specifica A9: un `flock` esclusivo su `<tasks_dir>/.ai-orch.lock` attorno a ogni comando mutante;
  - un hash del bundle del task, con `--expect-task-hash` su `transition`;
  - scritture atomiche per i file dei task e `PROGRESS.md`;
  - un rifiuto chiaro su Windows;
  - `tasks list --json` espone `bundle_sha256` per ogni task.
- **Verification:**
  - Test: due transizioni concorrenti dello stesso task → esattamente una vince e l'altra viene rifiutata (hash obsoleto o attesa del lock, poi rifiuto); un hash obsoleto → rifiutato con il file invariato; un crash a metà scrittura (simulato) lascia il file vecchio o quello nuovo, mai uno troncato.

### 06.9 - Bridge VS Code: mappa completa degli handler, rifiuto su codice diverso da zero, sincronizzazione `dist-webview`, nessun percorso cablato, scelta multi-root (V1, V2)

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Completamento bridge VS Code · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 06.8 · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/cli-client.ts`, `src/views/dashboard-panel.ts`, `src/extension.ts`, `package.json`, `esbuild.config.mjs`, `dist-webview/**`
- **Goal:** Implementare il §2.5 della specifica.
- **Verification:**
  - `npm run compile` termina senza errori (ora include `sync-webview`).
  - Uno unit test verifica che ogni metodo di `api.ts` abbia un handler.
  - Dal vivo in un Extension Development Host:
    - aprire la dashboard, attivare un'anteprima e un'azione rifiutata, e verificare la visualizzazione dell'errore;
    - registrare nella specifica se il `confirm()` nativo è bloccato (V3).
