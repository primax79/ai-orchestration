# 17 — Gli use case guidano i task — Piano di implementazione

**Spec:** [`specs/use-cases-drive-tasks.md`](../specs/use-cases-drive-tasks.md) (v2, rivista da Codex)
**Perché:** richiesta del proprietario 2026-10-27 (nota N072), priorità massima: i task nascono dagli use case, un use
case dipende dai suoi task (molti a molti), la validazione gira solo sugli use case pronti, il lavoro nuovo parte dagli
use case. Caso concreto: in git-code-rag due campagne hanno segnato come `failing` use case in bozza senza task.
**Decisione:** Q011 risposta A (approvazione separata dallo stadio derivato), 2026-10-27.
**Relazione con T069:** T069 (campagna solo sugli use case attivi, untested non è failing) è un tampone già in corso;
17.6 lo sostituisce con l'ambito basato sulla prontezza e ne conserva la regola su `untested`.

## Tasks

### 17.4 - Task che nascono dagli use case; kind facoltativo; migrazione dei chiamanti

- **Status:** `delivered` (2026-10-28, kilo: implementati `--use-case` e `--from-use-case [--steps]` per `tasks new` e `tasks child add`, `--kind` facoltativo con predefinito `feature` o avviso su stderr, avvisi di `validate` e aggiornamento dei chiamanti interni e di `CLI_DESCRIPTION`) · **Short:** Task da use case · **Size:** M · **Depends on:** 17.2
- **Goal:** spec §2: `tasks new --use-case` / `--from-use-case` (precompilazione), anche per i task di iniziativa; `--kind` facoltativo con avviso; avvisi di validate; aggiornati i chiamanti (backend UI, broker `tasks.new`, `orchestration_runs.py`, follow-up interni) senza rompere chi non passa i nuovi campi.
- **Verification:** `tasks new --use-case UC001,UC004` e `--from-use-case UC001 [--steps 2-3]` (anche per blocchi di iniziativa tramite `tasks child add` e `tasks new --parent`) collegano gli use case alla creazione nell'ordine canonico dei campi/segmenti, precompilano titolo, Goal e Verification, rifiutano use case sconosciuti o `deprecated`, impostano `kind: feature` come predefinito con `--use-case`/`--from-use-case` ed emettono avviso su stderr senza errore quando `kind` è omesso; `validate` emette avvisi (mai errori) per task `feature`/`fix` senza use case, use case `approved` senza task collegati e riferimenti a use case sconosciuti o `deprecated`; i chiamanti interni (`answer_question` follow-up, `orchestration_runs.py` triage) passano `kind` mantenendo la retrocompatibilità per chiamate senza `kind`.

### 17.8 - Flusso use-case-first nelle skill e ricerca

- **Status:** `open` · **Short:** Skill use-case-first · **Size:** M · **Depends on:** 17.4
- **Goal:** spec §4: `use-cases search` (testo, attore, spec citate, task sugli stessi percorsi); task-pipeline e orchestration-workflow dai template, rigenerati con `--check`, rigenerata la skill legata di kilo-mcp.

### 17.9 - API del backend UI per collegamenti e stadi

- **Status:** `in progress` (2026-10-28; operator) · **Short:** API use case-task · **Size:** S · **Depends on:** 17.5, 17.7
- **Goal:** backend di ai-orchestration-ui: campi stage/approval/collegamenti/coda in JSON, test di compatibilità del JSON.

### 17.10 - UI web ed estensione VS Code

- **Status:** `open` · **Short:** UI use case e task · **Size:** M · **Depends on:** 17.9
- **Goal:** badge di stadio e approvazione, task collegati, filtro per use case, coda di rivalidazione, nella UI web e nell'estensione (sync del webview); il proprietario la valida usandola.

### 17.11 - Documentazione e spec superata

- **Status:** `open` · **Short:** Documentazione use case · **Size:** S · **Depends on:** 17.5, 17.7
- **Goal:** nota "Superseded fields" in `use-case-management-and-ai-validation.md`, help dei comandi, regole di task-pipeline, guida di migrazione.

### 17.12 - Migrazione ai-orchestration

- **Status:** `delivered` (2026-10-28; operator; 2026-10-28; Applicata (76506eb): 109 collegamenti su 91 task, 37 use case con approval proposed; validate ok. Al proprietario: approvare gli use case) · **Verify-by:** owner · **Short:** Migrazione ai-orchestration · **Size:** S · **Depends on:** 17.3, 17.5, 17.6
- **Goal:** adopt-links e collegamenti mancanti per UC001-UC037; anteprima, report, validate pulito.

### 17.13 - Migrazione ai-swissknife

- **Status:** `waiting` (2026-10-28; operator; 2026-10-28; Gli use case di ai-swissknife puntano a iniziative intere: serve T085 (Espansione iniziative)) · **Short:** Migrazione ai-swissknife · **Size:** S · **Depends on:** 17.3, 17.5, 17.6
- **Goal:** come 17.12 per UC001-UC034 di ai-swissknife.

## Closed

### 17.1 - Lettura del collegamento e proiezione derivata (sola lettura)

- **Status:** `done` (2026-10-27, kilo, commit `da222a6`: proiezione derivata task↔use case, avvisi validate e output show; done 2026-10-27, verifier ai-coding-tools-d8) · **Short:** Proiezione collegamenti · **Size:** M · **Depends on:** -
- **Goal:** spec §1: lettura di `use-cases:` (task) e `**Use cases:**` (blocchi di iniziativa), calcolo di `linked-tasks` derivato senza scrivere; `validate` segnala le differenze con quello scritto e gli id sconosciuti; `tasks show` / `use-cases show` mostrano i collegamenti nei due sensi.
- **Verification:** `compute_use_case_links(tasks_dir)` restituisce `UseCaseLinkProjection` (`{uc_id: [task_id ordinati]}`, task `dropped` inclusi e marcati in `dropped_tasks`/`details`, mappa inversa `reverse`/`by_task` `{task_id: [uc_id]}`); chiavi JSON stabili: in `tasks show --json` (`task.use_cases`, `task.use_cases_details` / `task.linked_use_cases` con `id`, `title`, `short_title`, `status`, `last_verdict`, `deprecated`, `known`, `external`) e in `use-cases show --json` (`use_case.linked_tasks`, `use_case.derived_linked_tasks`, `use_case.linked_tasks_details` / `use_case.derived_linked_tasks_details` con `id`, `title`, `short_title`, `state`, `canonical_state`, `dropped`, `use_case.written_linked_tasks`, `use_case.linked_tasks_differ`, `use_case.written_linked_tasks_note`).

### 17.2 - Comandi link/unlink e riscrittura derivata in sync-index

- **Status:** `done` (2026-10-27, kilo, commit `4cde307`: comandi `tasks link`/`unlink` con anteprima/apply e riscrittura transazionale derivata di `linked-tasks` in `sync-index` con guardia pre-adozione; done 2026-10-28, verifier ai-coding-tools-87) · **Short:** Link e riscrittura derivata · **Size:** M · **Depends on:** 17.1
- **Goal:** spec §1: `tasks link`/`unlink` (anteprima/apply), inserimento rispettando l'ordine dei campi e la posizione del segmento nei blocchi; riscrittura mirata di `linked-tasks` dentro il piano di `sync-index` (hash, transazione, rollback, evento `use_case.links_changed`); mai su un albero non valido.
- **Verification:** `tasks link` e `tasks unlink` (anteprima predefinita, `--apply --expect-plan-hash`) scrivono `use-cases:` dopo `run-id` e prima di `short` sui task emergenti e `**Use cases:**` subito dopo `**Depends on:**` nei blocchi di iniziativa, aggiornando nella stessa transazione i `linked-tasks:` degli use case interessati; `sync-index` include le riscritture mirate di `linked-tasks:` nel piano con hash unico, rollback atomico, rifiuto su albero con errori di `validate`, emissione di `use_case.links_changed` e guardia pre-adozione ("run use-cases adopt-links first" per i 36 use case con `linked-tasks` scritti e non ancora adottati).

### 17.3 - Migrazione adopt-links

- **Status:** `done` (2026-10-28, kilo, commit `f973708`: comando `use-cases adopt-links` fail-closed con `--skip-unknown`, snapshot con manifesto sha256 in `_reviews/adopt-links-<timestamp>/` e applicazione atomica con rollback; done 2026-10-28, verifier ai-coding-tools-87) · **Short:** Migrazione adopt-links · **Size:** S · **Depends on:** 17.2
- **Goal:** spec §1: `use-cases adopt-links` porta i `linked-tasks` attuali sui task (unione), si ferma sugli id sconosciuti, istantanea in `_reviews/`; nessun collegamento perso (test su copia di git-code-rag).
- **Verification:** `use-cases adopt-links` (anteprima predefinita, `--apply --expect-plan-hash`) unisce i `linked-tasks` degli use case nei campi `use-cases:` / `**Use cases:**` dei task tramite lo scrittore di 17.2, rifiuta in modo fail-closed id sconosciuti/non canonici/cross-workspace salvo `--skip-unknown` (registrandoli nel report), salva una copia dei file toccati con `manifest.json` (sha256) in `tasks/_reviews/adopt-links-<timestamp>/` prima della scrittura atomica con rollback, sblocca la guardia pre-adozione di `sync-index` preservando gli elenchi di task collegati; verificato anche su copie di `ai-orchestration/tasks` (36/37 use case con link, 109 link adottati, 0 sconosciuti) e `git-code-rag/tasks` (32/41 use case con link, 71 link adottati, 0 sconosciuti) con `sync-index` successivo a 0 riscritture.

### 17.5 - Ciclo di vita: approvazione e stadio derivato

- **Status:** `done` (2026-10-28, kilo, commit `2b07859`: campo `approval`, migrazione atomica `use-cases migrate-lifecycle` con backfill di `last-verdict` e snapshot in `_reviews/`, calcolo puro di `stage` e visualizzazione in `list`/`show`/`00-INDEX.md`; done 2026-10-28, verifier ai-coding-tools-87) · **Short:** Stadio degli use case · **Size:** M · **Depends on:** 17.1
- **Goal:** spec §3 secondo la risposta a Q011: campo `approval` con migrazione da `status` (verdetto in `last-verdict`, nessun log perso), `stage` come funzione pura; mostrato da show/list/indice.

### 17.6 - Validazione solo sugli use case pronti

- **Status:** `done` (2026-10-28, kilo, commit `e538a28`: rifiuto exit 2 in `use-cases validate` se non pronto salvo `--force` registrato e con evento `use_case.validated`, campagne limitate agli use case pronti con sezione "Not ready (N/M)" ed esclusione di `untested` dal denominatore di prontezza; done 2026-10-28, verifier ai-coding-tools-87) · **Short:** Validazione solo se pronti · **Size:** M · **Depends on:** 17.5, T069
- **Goal:** spec §5: `use-cases validate` rifiuta se non pronto (salvo `--force` registrato); campagne solo sugli use case in ambito, gli altri "Not ready (N/M)"; sostituisce l'ambito di T069 tenendo la regola `untested`; il punteggio di prontezza esclude gli `untested` dal denominatore o li mostra a parte (osservazione di ai-coding-tools-ea nella validazione di T069: 75% = 24/32 con 7 untested).

### 17.7 - Regressione: rivalidazione e chiusura sicura dei task

- **Status:** `done` (2026-10-28, kilo, commit `75c49e4`: scrittura transazionale di `revalidation: pending` con evento `use_case.revalidation_requested`, coda `use-cases queue` ordinata dal più vecchio e guardia di chiusura sicura su `verified`/`done` con rifiuto exit 2, evento `task.transition_refused` e override `--owner-approved`; done 2026-10-28, verifier ai-coding-tools-87) · **Short:** Regressione use case · **Size:** M · **Depends on:** 17.5
- **Goal:** spec §5: `revalidation: pending` e coda `use-cases queue`; un task si chiude con uno use case fallito solo se questo è passato dopo la sua consegna (o `--owner-approved`); eventi registrati.

### 17.14 - Migrazione git-code-rag (con la sua sessione)

- **Status:** `done` (2026-10-28; guardia di validate verificata su UC031; done 2026-10-28, verifier ai-coding-tools-58) · **Short:** Migrazione git-code-rag · **Size:** S · **Depends on:** 17.3, 17.5, 17.6
- **Goal:** la sessione di git-code-rag applica la migrazione ai suoi 41 use case e la valida; spec §7 punto 7.
