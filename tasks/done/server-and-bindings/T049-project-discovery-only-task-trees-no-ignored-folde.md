# T049 Rilevamento dei progetti: solo alberi tasks, nessuna cartella ignorata o symlink; configurazione di esclusione; nascondere i progetti vuoti

- id: T049
- title: Rilevamento dei progetti: solo alberi tasks, nessuna cartella ignorata o symlink; configurazione di esclusione; nascondere i progetti vuoti
- category: server-and-bindings
- priority: P1
- priority-reason: Il visualizzatore dei task di porting_liferay elenca 418 progetti di cui 417 vuoti: la vista multi-progetto lì è inutilizzabile
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N048 (porting_liferay)
- paths: ../vscode-ai-orchestration/src/project-resolver.ts, ../vscode-ai-orchestration/src/extension.ts, ../ai-orchestration-ui/backend/projects.py, ../ai-orchestration-ui/frontend/src/components/Navbar.tsx, scripts/orchestration_registry.py
- handoff: Leggere tasks/server-and-bindings/T049-project-discovery-only-task-trees-no-ignored-folde.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: owner
- use-cases: UC030
- short: Igiene rilevamento progetti

## Goal

Il rilevamento dei progetti (resolver di VS Code, backend della UI, registry discover) propone solo le cartelle che contengono tasks/00-INDEX.md, non scende mai nelle cartelle ignorate da git e non segue mai i symlink; una configurazione versionata per workspace (ad es. glob include/exclude sotto [workspace.discovery] nell'orchestration.toml del workspace, oppure un file .ai-orchestration/projects-ignore) filtra ulteriormente; i selettori nascondono di default i progetti con zero task tramite un interruttore 'show empty'. La configurazione di esclusione accetta sia nomi di progetto sia percorsi, dove un percorso ignora un intero sottoalbero di cartelle (ad es. `liferay62/`, `source_codes/`) con tutto ciò che contiene (owner, tramite porting_liferay). Riprodurre prima su ~/works/gcube/porting_liferay (in sola lettura) e riportare la causa radice delle 417 voci.

## Steps

- [x] **Analisi della causa radice su `~/works/gcube/porting_liferay` (in sola lettura):**
  1. `is_git_ignored(path, ws_path)` in tutte e tre le codebase (`orchestration_registry.py`, `backend/projects.py`, `src/project-resolver.ts`) iniziava con `if (path / ".git").exists(): return False`. Ogni volta che una directory ignorata da git in `porting_liferay` (come `/ansible-playbooks/`, `security_audit/`, `/liferay62/`, `/conductor/`, `/source_codes/`) era a sua volta un clone git annidato, `is_git_ignored` restituiva `False` invece di controllare per `ws_path` il file `.gitignore`. Una volta che la scansione entrava in quel repository git annidato, `_git_repo_root(path)` si risolveva nel `.git` interno, perciò nulla al suo interno veniva ignorato da `ws_path/.gitignore` — esponendo circa 410 cartelle di ruoli Ansible (`roles/<role>/tasks/main.yml`) più i repository annidati.
  2. `os.walk(str(ws_path))` in Python include le directory con symlink (`libs-jdk17 -> ~/works/gcube_repos/gcube-jdk17` e `security_audit/private/services -> ~/works/gcube_audit/services`) in `dirs` e chiamava `.resolve()` su di esse.
  3. `ProjectResolver` sia in `backend/projects.py` sia in `src/project-resolver.ts` metteva in cache `_cached_projects` / `_cachedProjects` indefinitamente senza controllare gli mtime di `.gitignore` o della configurazione di esclusione, e `invalidateTasksCache()` non svuotava mai `_cachedProjects` (mantenendo in cache nell'Extension Host attivo di VS Code le voci obsolete precedenti a T048 anche dopo il ricaricamento della webview).
- [x] Correggere `is_git_ignored` in `ai-orchestration/scripts/orchestration_registry.py`, `ai-orchestration-ui/backend/projects.py` e `vscode-ai-orchestration/src/project-resolver.ts` in modo che le regole esplicite di `.gitignore` nel workspace o nel repository padre escludano sempre le directory `.git` annidate, mentre i wildcard generici alla radice (`*` o `/*` nei workspace contenitore con allowlist come `ai-coding-tools`) continuino a consentire i repository annidati.
- [x] Rifiutare i symlink (`is_symlink()` / `isSymbolicLink()`) su cartelle, `tasks/` e `tasks/00-INDEX.md`, e richiedere `tasks/00-INDEX.md` in tutte e tre le implementazioni di rilevamento.
- [x] Implementare `WorkspaceDiscoveryFilter` (`load_workspace_discovery_filter` / `loadWorkspaceDiscoveryFilter`) con supporto per `.ai-orchestration/projects-ignore`, `.ai-orchignore` e `[workspace.discovery]` (`include` / `exclude` / `ignore` in `orchestration.toml`), confrontando sia i nomi/slug dei progetti sia i sottoalberi di cartelle (ad es. `liferay62/`, `source_codes/`, `porting_liferay_cnr/modules/`) con negazione `!`, più invalidazione automatica della cache al variare degli mtime della configurazione o del gitignore.
- [x] Nascondere di default i progetti con 0 task attivi nella Web UI (`Navbar.tsx`) e nel QuickPick `aiOrchestration.selectProject` di VS Code (`extension.ts`), con un interruttore `Show empty (+N)` / `Hide empty (N)`.

## Verification

- `pytest scripts/test_orchestration_registry.py` in `ai-orchestration` (12 passati)
- `.venv/bin/pytest backend/test_multi_project.py && npm --prefix frontend run build` in `ai-orchestration-ui` (9 passati, frontend compilato)
- `npm run sync-webview && npm run compile && node scripts/test-multi-project.mjs` in `vscode-ai-orchestration` (tutte le 6 suite di test multi-progetto passate; `out/extension.js` compilato e `dist-webview/` sincronizzati in `~/.vscode/extensions/alfredooliviero.vscode-ai-orchestration-0.6.0/`)
- Verifica in sola lettura su `~/works/gcube/porting_liferay`, `~/works/d4science-python-library` e `~/works/ai-coding-tools` attraverso tutti e tre i resolver.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
