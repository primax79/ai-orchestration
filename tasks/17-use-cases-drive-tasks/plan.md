# 17 — Gli use case guidano i task — Piano di implementazione

**Spec:** [`specs/use-cases-drive-tasks.md`](../specs/use-cases-drive-tasks.md) (v2, rivista da Codex)
**Perché:** richiesta del proprietario 2026-10-27 (nota N072), priorità massima: i task nascono dagli use case, un use
case dipende dai suoi task (molti a molti), la validazione gira solo sugli use case pronti, il lavoro nuovo parte dagli
use case. Caso concreto: in git-code-rag due campagne hanno segnato come `failing` use case in bozza senza task.
**Decisione aperta:** Q011 (approvazione separata dallo stadio): blocca 17.5; il resto procede.
**Relazione con T069:** T069 (campagna solo sugli use case attivi, untested non è failing) è un tampone già in corso;
17.6 lo sostituisce con l'ambito basato sulla prontezza e ne conserva la regola su `untested`.

## Tasks

### 17.1 - Lettura del collegamento e proiezione derivata (sola lettura)

- **Status:** `open` · **Short:** Proiezione collegamenti · **Size:** M · **Depends on:** -
- **Goal:** spec §1: lettura di `use-cases:` (task) e `**Use cases:**` (blocchi di iniziativa), calcolo di `linked-tasks` derivato senza scrivere; `validate` segnala le differenze con quello scritto e gli id sconosciuti; `tasks show` / `use-cases show` mostrano i collegamenti nei due sensi.

### 17.2 - Comandi link/unlink e riscrittura derivata in sync-index

- **Status:** `open` · **Short:** Link e riscrittura derivata · **Size:** M · **Depends on:** 17.1
- **Goal:** spec §1: `tasks link`/`unlink` (anteprima/apply), inserimento rispettando l'ordine dei campi e la posizione del segmento nei blocchi; riscrittura mirata di `linked-tasks` dentro il piano di `sync-index` (hash, transazione, rollback, evento `use_case.links_changed`); mai su un albero non valido.

### 17.3 - Migrazione adopt-links

- **Status:** `open` · **Short:** Migrazione adopt-links · **Size:** S · **Depends on:** 17.2
- **Goal:** spec §1: `use-cases adopt-links` porta i `linked-tasks` attuali sui task (unione), si ferma sugli id sconosciuti, istantanea in `_reviews/`; nessun collegamento perso (test su copia di git-code-rag).

### 17.4 - Task che nascono dagli use case; kind facoltativo; migrazione dei chiamanti

- **Status:** `open` · **Short:** Task da use case · **Size:** M · **Depends on:** 17.2
- **Goal:** spec §2: `tasks new --use-case` / `--from-use-case` (precompilazione), anche per i task di iniziativa; `--kind` facoltativo con avviso; avvisi di validate; aggiornati i chiamanti (backend UI, broker `tasks.new`, `orchestration_runs.py`, follow-up interni) senza rompere chi non passa i nuovi campi.

### 17.5 - Ciclo di vita: approvazione e stadio derivato

- **Status:** `waiting` · **Decider:** Q011 · **Waiting-on:** question:Q011 · **Short:** Stadio degli use case · **Size:** M · **Depends on:** 17.1, Q011
- **Goal:** spec §3 secondo la risposta a Q011: campo `approval` con migrazione da `status` (verdetto in `last-verdict`, nessun log perso), `stage` come funzione pura; mostrato da show/list/indice.

### 17.6 - Validazione solo sugli use case pronti

- **Status:** `open` · **Short:** Validazione solo se pronti · **Size:** M · **Depends on:** 17.5, T069
- **Goal:** spec §5: `use-cases validate` rifiuta se non pronto (salvo `--force` registrato); campagne solo sugli use case in ambito, gli altri "Not ready (N/M)"; sostituisce l'ambito di T069 tenendo la regola `untested`.

### 17.7 - Regressione: rivalidazione e chiusura sicura dei task

- **Status:** `open` · **Short:** Regressione use case · **Size:** M · **Depends on:** 17.5
- **Goal:** spec §5: `revalidation: pending` e coda `use-cases queue`; un task si chiude con uno use case fallito solo se questo è passato dopo la sua consegna (o `--owner-approved`); eventi registrati.

### 17.8 - Flusso use-case-first nelle skill e ricerca

- **Status:** `open` · **Short:** Skill use-case-first · **Size:** M · **Depends on:** 17.4
- **Goal:** spec §4: `use-cases search` (testo, attore, spec citate, task sugli stessi percorsi); task-pipeline e orchestration-workflow dai template, rigenerati con `--check`, rigenerata la skill legata di kilo-mcp.

### 17.9 - API del backend UI per collegamenti e stadi

- **Status:** `open` · **Short:** API use case-task · **Size:** S · **Depends on:** 17.5, 17.7
- **Goal:** backend di ai-orchestration-ui: campi stage/approval/collegamenti/coda in JSON, test di compatibilità del JSON.

### 17.10 - UI web ed estensione VS Code

- **Status:** `open` · **Short:** UI use case e task · **Size:** M · **Depends on:** 17.9
- **Goal:** badge di stadio e approvazione, task collegati, filtro per use case, coda di rivalidazione, nella UI web e nell'estensione (sync del webview); il proprietario la valida usandola.

### 17.11 - Documentazione e spec superata

- **Status:** `open` · **Short:** Documentazione use case · **Size:** S · **Depends on:** 17.5, 17.7
- **Goal:** nota "Superseded fields" in `use-case-management-and-ai-validation.md`, help dei comandi, regole di task-pipeline, guida di migrazione.

### 17.12 - Migrazione ai-orchestration

- **Status:** `open` · **Short:** Migrazione ai-orchestration · **Size:** S · **Depends on:** 17.3, 17.5, 17.6
- **Goal:** adopt-links e collegamenti mancanti per UC001-UC037; anteprima, report, validate pulito.

### 17.13 - Migrazione ai-swissknife

- **Status:** `open` · **Short:** Migrazione ai-swissknife · **Size:** S · **Depends on:** 17.3, 17.5, 17.6
- **Goal:** come 17.12 per UC001-UC034 di ai-swissknife.

### 17.14 - Migrazione git-code-rag (con la sua sessione)

- **Status:** `open` · **Short:** Migrazione git-code-rag · **Size:** S · **Depends on:** 17.3, 17.5, 17.6
- **Goal:** la sessione di git-code-rag applica la migrazione ai suoi 41 use case e la valida; spec §7 punto 7.
