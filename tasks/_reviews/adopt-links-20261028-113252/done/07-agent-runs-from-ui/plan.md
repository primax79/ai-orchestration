# 07 - Esecuzioni degli agenti dal piano di controllo (scegliere chi svolge il lavoro)

- **Short:** Esecuzioni degli agenti

> **Derived from:** [`../specs/agent-runs-from-ui.md`](../../specs/agent-runs-from-ui.md) (v2). Leggere prima la specifica; questo piano non la ripete.
>
> **Requires:** iniziativa 06 per ogni task della UI (07.7+). I task principali (07.1–07.6) possono iniziare non appena le dipendenze sui file lo consentono.

## Ondate

| Ondata | Task |
| --- | --- |
| A (può girare in parallelo all'ondata 1 della 06) | 07.1 (`orchestration_config.py`; è in conflitto con 06.6, quindi va eseguito prima o dopo, mai contemporaneamente) |
| B | 07.2 (nuovo `orchestration_runs.py`) |
| C | 07.3, poi 07.4 (stesso file, sequenziali) |
| D | 07.5 (self, dal vivo) |
| E (dopo il completamento della 06) | 07.6 → 07.7 → 07.8 → 07.9 |

## Tasks (One Task = One Commit)

## Modifiche dopo la revisione 2 (2026-10-16)

La specifica ora si apre con il §0 "Amendments after review 2" (R1–R14). Da esso discendono queste modifiche ai task, e l'ordine delle corsie si trova in `../06-control-plane-safety/plan.md`:

- **07.1** copre anche:
  - il segnaposto `{effort}` (R3);
  - `--diff`/`--expect-hash` su `set-routing` e `set-profile` (specifica 06 A10).

  È stato avviato prima della revisione; il delta segue nella stessa sessione Kilo.
- **07.2** copre anche:
  - R1: un `plan_hash` vincolante in `preview`;
  - R4: le modalità consentite per stato;
  - R8: l'hash del bundle del task, riutilizzando la funzione di hash di 06.10, **quindi 07.2 dipende da 06.10**;
  - R10: il rifiuto della piattaforma;
  - R13: riferimenti ai segreti e redazione.
- **07.3** copre anche:
  - R2: identità di processo separate;
  - R9: blocchi di log con offset logici;
  - R11: Claude rifiuta l'avvio senza un `allowed_tools` configurato.
- **07.4** copre anche:
  - R5: le modalità di verifica, incluso il panel;
  - R6: `run mark-delivered`;
  - R7: gli invarianti degli artefatti, aggiungendo ai test un branch che avanza, un reset e `target_run: none` con deriva di HEAD;
  - R12: pulizia lungo le catene di continuazione.
- **07.5** deve dimostrare un'esecuzione reale con test e commit sotto la policy di permessi scelta dall'owner (R11).
- **07.8** dipende da **07.7** (`api.ts`, `types.ts`, `dist` condivisi).
- **07.9** aggiunge `src/cli-client.ts` e i relativi test ai focus files.

## Decisioni in attesa

| Chiave | Domanda | Blocca | Decisore |
| --- | --- | --- | --- |
| R11 | **Deciso il 2026-10-17 (Q001 → A):** allow-list per modalità. `execute` e `verify` ricevono git, i test runner e i tool sui file; `orchestrate` riceve anche i tool kilo-mcp. Implementato come impostazioni predefinite integrate nell'adapter in 07.12. | — | owner |

## Closed

### 07.1 - `config set-routing`, aggiornatore TOML chirurgico, schema `[tools.<t>.headless]`, testo corretto per il percorso di configurazione del progetto

- **Status:** `done` (2026-10-16) · **Short:** Configurazione del routing · **Profile:** `deep-reasoning` · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py`, `.../scripts/test_orchestration_config.py`, `bin/ai-orch` (testo del catalogo), `docs/05-orchestration-config-schema.md`
- **Goal:** Implementare il §9 della specifica:
  - un aggiornatore chirurgico usato sia da `set-routing` sia da `set-profile`;
  - lo schema headless, con i segnaposto `{cwd}`, `{model}`, `{variant}`, `{session_id}`, `{permission_mode}`, `{sandbox}`, `{prompt_file}`;
  - il vero percorso di configurazione indicato nel blocco `AGENTS.md`, nell'aiuto di `init-project` e nel catalogo.
- **Verification:** Test:
  - `set-routing` e `set-profile` su una configurazione temporanea con commenti, righe vuote e tabelle non correlate: tutto tranne i valori target è identico byte per byte;
  - un segnaposto non valido viene rifiutato;
  - il blocco generato indica `find_project_config_path(...)`.

### 07.2 - Motore di esecuzione A: registro, locking, record, validazione delle richieste, prompt, `options`/`preview`/`list`/`show`

- **Status:** `done` (2026-10-17) · **Short:** Registro motore di esecuzione · **Profile:** `deep-reasoning` · **Depends on:** 07.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py` (nuovo), `scripts/test_orchestration_runs.py` (nuovo), `bin/ai-orch`
- **Goal:** Specifica §3 (risoluzione, modalità, prompt, ambito limitato a `T###`), §4 (`options`, `preview`, `list`, `show`), §5.1, §5.2 (lock, guardie, record monotoni). Ancora nessuna creazione di processi.
- **Verification:** Test:
  - la catena di risoluzione in tutti e quattro i livelli;
  - ogni guardia rifiuta indicando il motivo (`NN.T`, stato errato, tool disabilitato o mancante, stesso task attivo, stessa cwd attiva);
  - `preview` è privo di effetti collaterali (hash dell'albero del workspace invariato);
  - `.git/info/exclude` riceve `.ai-orchestration/`, e l'avvio viene rifiutato quando non può essere ignorato;
  - la validazione di `run_id` rifiuta il path traversal.

### 07.3 - Motore di esecuzione B: supervisore, adapter (prompt via stdin/file), annullamento e riconciliazione delle esecuzioni perse con terminazione del gruppo di processi

- **Status:** `done` (2026-10-17) · **Short:** Supervisore e adapter esecuzioni · **Profile:** `deep-reasoning` · **Depends on:** 07.2 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`, `scripts/fixtures/runs/stub_agent.py` (nuovo)
- **Goal:** Specifica §4 (`start`, `logs`, `cancel`), §5.3, §5.7 (adapter, con l'agente stub configurato tramite `[tools.<t>.headless]`), e la transizione del task a `in progress` all'avvio riuscito di un'esecuzione execute (§3 "Task state ownership").
- **Verification:** Test contro l'agente stub (che può attendere in sleep, generare un processo nipote, scrivere eventi e terminare con codice 0 o 1):
  - gli esiti riusciti e falliti vengono registrati;
  - l'annullamento non lascia in vita alcun processo del gruppo (verificare anche il processo nipote);
  - SIGKILL sul supervisore → il successivo `list` segna `lost` **e** il gruppo dell'agente non esiste più;
  - un PID riutilizzato con un tempo di avvio diverso non viene terminato (simulato);
  - il prompt non compare mai nell'argv di `ps`;
  - chiamate `start` concorrenti per lo stesso task → esattamente una vince.

### 07.4 - Motore di esecuzione C: isolamento worktree, target di verifica, parsing del verdetto e `apply-verdict`, invarianti di continuazione, `cleanup`

- **Status:** `done` (2026-10-17) · **Short:** Worktree e verdetti esecuzioni · **Size:** L · **Profile:** `deep-reasoning` · **Depends on:** 07.3 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:** Specifica §5.4, §5.5, §5.6 e `run cleanup`.
- **Verification:** Test in repository git temporanei:
  - un repository sporco viene rifiutato (`--allow-dirty-base` emette un avviso);
  - `paths` multi-repo vengono rifiutati;
  - il worktree e il branch vengono creati e `base_commit`/`final_commit` registrati;
  - la verifica gira in un worktree usa e getta in stato detached di `final_commit`;
  - la guardia di indipendenza regge;
  - un verdetto viene estratto solo dal messaggio finale;
  - `apply-verdict` viene rifiutato dopo che il file del task è cambiato;
  - la continuazione blocca i campi e rifiuta verify→execute e un worktree mancante;
  - `cleanup` rifiuta un branch non unito senza `--discard`.

### 07.6 - Backend UI: endpoint di esecuzione e di configurazione

- **Status:** `done` (2026-10-17) · **Short:** Endpoint esecuzioni e config · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 07.4, 06.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Specifica §6.
- **Verification:**
  - Test tramite HTTP con l'agente stub configurato in una configurazione di workspace temporanea: options → preview → start → logs (incrementali) → cancel → continue → apply-verdict.
  - Dal vivo con `curl` su un server in esecuzione.

### 07.7 - Frontend: finestra di dialogo Run con anteprima dal vivo, pannello delle esecuzioni del task, scheda Runs

- **Status:** `done` (2026-10-17) · **Short:** Dialogo Run e scheda Runs · **Size:** L · **Profile:** `bulk-execution` · **Depends on:** 07.6, 06.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Specifica §7, ad eccezione della scheda Config.
- **Verification:**
  - `npm run build` termina senza errori.
  - Dal vivo con il server MCP Playwright su un workspace temporaneo con l'agente stub:
    - avviare un'esecuzione e visualizzare il log;
    - annullarla;
    - continuarla;
    - applicare un verdetto;
    - verificare il rifiuto per l'uso dello stesso tool in fase di verifica.

### 07.8 - Frontend: modifica nella scheda Config (routing e matrice profilo/modello)

- **Status:** `done` (2026-10-17) · **Short:** Modifica scheda Config · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 07.6, 06.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/components/OrchestrationConfigurator.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/dist/**`
- **Goal:** Specifica §7 "Config tab".
- **Verification:** Dal vivo: modificare il routing e un profilo nell'ambito di progetto; il diff di `.ai-orchestration.local.toml` mostra esclusivamente quei valori.

### 07.10 - Core: il supervisore delle esecuzioni registra le domande bloccanti (R14, specifica 08 Q8)

- **Status:** `done` (2026-10-17) · **Short:** Domande dalle esecuzioni · **Size:** S · **Profile:** `deep-reasoning` · **Depends on:** 07.4, 08.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:**
  - Al termine di un'esecuzione, analizzare i blocchi ` ```ai-orch-question ` dal messaggio **finale** dell'assistente.
  - Registrare ciascuno nel workspace **principale** tramite l'API del motore `questions ask`. Il supervisore imposta autonomamente `asked-by` e `origin-run` e forza `blocks` al task dell'esecuzione.
  - Registrare gli id in `run.json` `questions`.
  - Un blocco malformato → registrato in `question_errors`, mai scartato silenziosamente.
- **Verification:** Test con l'agente stub che emette un blocco valido, un blocco malformato e un blocco che indica un altro task in `blocks` (forzato al task dell'esecuzione).

### 07.12 - Allow-list integrata per modalità per Claude (decisione A di Q001)

- **Status:** `done` (2026-10-17) · **Short:** Allow-list di Claude · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 07.10 (stesso file) · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`, `plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py` (schema headless: `allowed_tools` può essere per modalità), `docs/05-orchestration-config-schema.md`
- **Goal:**
  - Risposta A di Q001: l'adapter Claude fornisce un `allowed_tools` predefinito per modalità, usato quando la configurazione non ne imposta alcuno, cosicché l'avvio non viene più rifiutato (R11) per assenza di allow-list.
  - La configurazione può sovrascrivere per modalità con `[tools.claude.headless.allowed_tools] execute = [...]`, `verify = [...]` e `orchestrate = [...]`, oppure mantenere un'unica lista per tutte le modalità.
  - L'anteprima di Run mostra la lista effettiva e indica se proviene dalle impostazioni predefinite o dalla configurazione.
- **Impostazioni predefinite:**
  - **execute:** `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash(git status:*)`, `Bash(git diff:*)`, `Bash(git add:*)`, `Bash(git commit:*)`, `Bash(git log:*)`, `Bash(pytest:*)`, `Bash(python -m pytest:*)`, `Bash(uv run:*)`, `Bash(npm test:*)`, `Bash(npm run build:*)`;
  - **verify:** uguale a execute, meno `Edit` e `Write`;
  - **orchestrate:** il set di execute più `mcp__kilo-mcp__*`.
- **Verification:**
  - Test: viene applicato il valore predefinito quando la configurazione non ne ha; gli override per modalità e a lista singola funzionano; l'anteprima mostra l'origine della lista; non compare alcun flag `--dangerously-*`.
  - Dal vivo: `run preview --tool claude --mode execute` su questo repository mostra la lista predefinita.

### 07.5 - Cattura dal vivo con le vere CLI: id di sessione, Final Report, verdetto, continue; correzione della tabella dei flag

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Cattura CLI dal vivo · **Size:** M · **Profile:** `deep-reasoning` · **Executor:** `self` (orchestratore: richiede le vere CLI e l'autenticazione) · **Depends on:** 07.4 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/fixtures/runs/{claude,kilo,codex}-*.jsonl` (nuovo), `scripts/test_orchestration_runs.py`, `tasks/specs/agent-runs-from-ui.md` (tabella §5.7)
- **Goal:** In un repository git temporaneo con un task a singolo passo, eseguire per ciascun tool:
  - un `execute`, un `--continue` e un `verify`;
  - salvare i flussi ripuliti come fixture;
  - finalizzare i parser per-tool di id di sessione / Final Report / verdetto;
  - correggere il §5.7 laddove i flag reali differiscano.
- **Verification:** I test sulle fixture passano e una riesecuzione dal vivo per ciascun tool mostra la cattura della sessione e l'atterraggio della continuazione nella medesima sessione.

### 07.9 - VS Code: handler delle esecuzioni e watcher delle esecuzioni

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Handler esecuzioni VS Code · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 07.7, 07.8, 06.9 · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/extension.ts`, `dist-webview/**`
- **Goal:** Specifica §8.
- **Verification:**
  - `npm run compile` termina senza errori e il test della mappa degli handler è verde.
  - Dal vivo in un Extension Development Host: avviare e annullare un'esecuzione stub dalla webview.

### 07.11 - Esecuzioni batch per i microtask

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Esecuzioni batch microtask · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 07.4, 10.4 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:** `../specs/timeline-gantt.md` §5 "Batch runs":
  - `run start --batch IDS` accetta microtask appartenenti a un solo repository target (rifiutato altrimenti);
  - un unico worktree;
  - il prompt elenca i microtask, richiedendo un commit per ciascun microtask;
  - il supervisore mappa i commit ai microtask (tramite un prefisso `T###` nel messaggio di commit);
  - lo stato di ciascun microtask viene impostato separatamente;
  - `mark-delivered` e verify funzionano per singolo microtask o per l'intero batch.
- **Verification:** Test con l'agente stub: tre microtask → tre commit → ciascuno `in progress` → `delivered`; un microtask privo di commit resta `in progress`, con la motivazione registrata.
