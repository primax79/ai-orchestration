# 15 - Specifiche guidate dai casi d'uso, definizione dei task e validazione del prodotto

> **Derived from spec:** [`../specs/use-case-management-and-ai-validation.md`](../../specs/use-case-management-and-ai-validation.md)  
> **Status:** `done` (2026-10-17)  
> **Requisito dell'owner:** Integrare i casi d'uso (Use Cases) come elemento trainante fondamentale per le specifiche dei task, i criteri di accettazione e le campagne autonome di validazione del prodotto basate su AI.

## Goal

Fornire supporto end-to-end per i **casi d'uso (`tasks/use-cases/UC###-<slug>.md`)**:
1. Top-down: i casi d'uso guidano i criteri di accettazione `## Goal` e `## Verification` dei task.
2. Bottom-up: i task implementati mantengono il collegamento inverso ai casi d'uso (`- linked-tasks: ...`).
3. Validazione AI autonoma: l'operatore può attivare il test AI di singoli casi d'uso oppure eseguire **campagne di validazione del prodotto** sull'intero sistema, con rilevamento automatico delle regressioni, log di audit e generazione con un clic di task emergenti a partire dalle lacune rilevate.
4. Gestione visuale: vista nella Web UI e nell'estensione VS Code per gestire i casi d'uso, ispezionare i punteggi di prontezza del prodotto e avviare le validazioni.

## Non-obiettivi

- Sostituire i framework di unit test di basso livello (pytest, vitest). I casi d'uso testano scenari end-to-end e percorsi utente.
- Memorizzare le esecuzioni dei test in database proprietari esterni; tutti i casi d'uso e i log di audit risiedono in file Markdown tracciati in Git.

---

## Tasks (One Task = One Commit)

## Closed

### 15.1 - Motore e modello dei dati (`tasks/use-cases/`, parser, validatore, intestazione dei task `- use-cases:`)
- **Status:** `done` (2026-10-17) · **Use cases:** UC001
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `tasks/specs/task-and-state-model.md`
- **Goal:**
  - Aggiungere `use-cases` a `RESERVED_DIRS`.
  - Aggiungere `use-cases` a `OPTIONAL_EXTENSION_FIELDS` nelle intestazioni dei task (`- use-cases: UC001, UC003`).
  - Implementare `discover_use_cases(tasks_dir)` per analizzare i file `UC###` (id, title, actor, status, priority, linked_tasks, verification_type, last_tested, last_verdict, scenario, verification_command, acceptance_criteria, validation_log).
  - Implementare `create_or_update_use_case` e `record_use_case_validation`.
  - Esporre `./bin/ai-orch use-cases list | show | create | record-validation`.
  - Scrivere gli unit test in `test_tasks_engine.py`.
- **Verification:** `pytest test_tasks_engine.py` passa al 100% (74 passati).

### 15.2 - Integrazione top-down nelle skill (`task-spec-authoring` e `task-pipeline`)
- **Status:** `done` (2026-10-17) · **Use cases:** UC001
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-spec-authoring/SKILL.md`, `plugins/architect-side/skills/task-pipeline/SKILL.md`, `plugins/architect-side/skills/task-pipeline/references/template.md`
- **Goal:**
  - Istruire l'Architect in `task-spec-authoring` ad ancorare direttamente le specifiche dei task e i criteri di accettazione `## Verification` ai casi d'uso del progetto (`tasks/use-cases/UC*.md`).
  - Aggiornare la skill `task-pipeline` per documentare il flusso bidirezionale: Use Cases ⇄ Specs ⇄ Tasks ⇄ Validation.
  - Aggiornare i template e rigenerare le skill generiche e vincolate.
- **Verification:** `python3 scripts/regenerate_generic_skills.py --check` e `python3 scripts/generate_skill_indices.py` passano.

### 15.3 - Esecutore di validazione AI autonoma (`ai-orch use-cases validate UC###`)
- **Status:** `done` (2026-10-17) · **Use cases:** UC002
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`
- **Goal:**
  - Implementato `validate_use_case_probe`: esegue il comando di verifica, catturando l'output e il codice di uscita.
  - Aggiorna `last-tested` e `last-verdict` sul file del caso d'uso, porta lo stato a `verified` (se superato) o `failing` (se fallito) e accoda il report strutturato a `## AI Validation Log`.
- **Verification:** Lo unit test `test_use_cases_validate_probe_and_campaign` passa.

### 15.4 - Esecutore della campagna di validazione a livello di prodotto (`ai-orch use-cases campaign`)
- **Status:** `done` (2026-10-17) · **Use cases:** UC003
- **Profile:** `deep-reasoning`
- **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `bin/ai-orch`
- **Goal:**
  - Implementato `run_validation_campaign`: itera su tutti i casi d'uso attivi (con filtro opzionale per attore).
  - Rileva le regressioni: segnala i casi d'uso che in precedenza passavano e ora falliscono.
  - Genera un report di validazione del prodotto con timestamp in `tasks/reports/validation-campaign-<timestamp>.md` con il punteggio complessivo di prontezza (% verificati).
- **Verification:** Lo unit test `test_use_cases_validate_probe_and_campaign` passa (punteggio di prontezza, file di report, elenco delle regressioni).

### 15.5 - Endpoint API REST e WebSocket del backend
- **Status:** `done` (2026-10-17)
- **Profile:** `bulk-execution`
- **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:**
  - Esporre `GET /api/use-cases`, `POST /api/use-cases`, `GET /api/use-cases/{id}`, `POST /api/use-cases/{id}/validate`, `POST /api/use-cases/campaign`.
  - Inviare eventi WebSocket in tempo reale (`use_cases_changed`).
- **Verification:** Gli unit test in `backend/test_server.py` passano al 100% (39 passati).

### 15.6 - Web UI e Webview VS Code: dashboard dei casi d'uso ed esecutore AI (scheda: `Use Cases & Validation`)
- **Status:** `done` (2026-10-17)
- **Profile:** `bulk-execution`
- **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/types.ts`, `frontend/src/api.ts`, `frontend/src/components/Navbar.tsx`, `frontend/src/components/UseCasesManager.tsx`, `frontend/src/components/UseCaseDetailModal.tsx`
- **Goal:**
  - Aggiunta la scheda di primo livello nella Navbar: **`Use Cases & Validation`**.
  - Riepilogo KPI: totale dei casi d'uso, punteggio di prontezza del prodotto (% verificati), falliti, in bozza.
  - Griglia / tabella filtrabile dei casi d'uso con badge di stato in tempo reale.
  - Modale "New Use Case".
  - Pulsante "Validate with AI" su ciascuna scheda e pulsante "Run Full Product Campaign".
  - Modale di dettaglio del caso d'uso: mostra i passi dello scenario, i task collegati con i relativi stati in tempo reale, il comando di verifica, la cronologia espandibile delle validazioni AI e il pulsante con un clic "Create Task from Gap" quando è in stato failing/partial.
- **Verification:** `npm run build` ha successo e viene renderizzato correttamente nel browser.

### 15.7 - TreeView nella barra laterale di VS Code (`aiOrchestration.useCasesView`)
- **Status:** `done` (2026-10-17)
- **Profile:** `bulk-execution`
- **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `package.json`, `src/views/task-tree-provider.ts`, `src/views/dashboard-panel.ts`, `src/extension.ts`
- **Goal:**
  - Aggiunto `aiOrchestration.useCasesView` nella barra laterale di VS Code sotto il contenitore AI Orchestration.
  - Mostra i casi d'uso con icone pass/fail/target; un clic apre il file Markdown del caso d'uso.
  - Collegato `CLI_COMMAND_MAP` per `getUseCases`, `getUseCase`, `createUseCase`, `validateUseCase`, `runValidationCampaign`.
  - Assemblato `dist-webview/` aggiornato e pacchettizzato/installato il VSIX v0.3.0.
- **Verification:** `npm run compile` e la pacchettizzazione VSIX passano; installato in VS Code.
