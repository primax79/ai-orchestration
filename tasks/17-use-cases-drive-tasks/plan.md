# 17 — Gli use case guidano i task — Piano di implementazione

**Spec:** [`specs/use-cases-drive-tasks.md`](../specs/use-cases-drive-tasks.md)
**Perché:** richiesta del proprietario 2026-10-27 (nota N072), priorità massima: i task nascono dagli use case, un use
case dipende dai suoi task (molti a molti), la validazione gira solo sugli use case pronti, il lavoro nuovo parte dagli
use case. Caso concreto: in git-code-rag due campagne hanno segnato come `failing` use case in bozza senza task.
**Assorbe:** T069 (la campagna esclude le bozze; ne è il primo passo, resta un task a sé).

## Tasks

### 17.1 - Collegamento molti a molti: task come fonte, linked-tasks derivato, migrazione

- **Status:** `open` · **Short:** Collegamento use case-task · **Size:** L · **Depends on:** -
- **Goal:** spec §1: `use-cases:` sui task e segmento `**Use cases:**` nei blocchi di iniziativa come fonte; `linked-tasks` dello use case riscritto dal motore a ogni sync; `tasks link`/`unlink`; `use-cases adopt-links` (anteprima/apply) che non perde collegamenti; avvisi di validate.

### 17.2 - Task che nascono dagli use case

- **Status:** `open` · **Short:** Task da use case · **Size:** M · **Depends on:** 17.1
- **Goal:** spec §2: `tasks new --use-case` / `--from-use-case` (precompilazione di Goal e Verification), stesse opzioni per i task di iniziativa; `kind` (default `feature` con `--use-case`); avvisi di validate per feature/fix senza use case e use case approvati senza task.

### 17.3 - Ciclo di vita dello use case: approvazione e stadio derivato

- **Status:** `open` · **Short:** Stadio degli use case · **Size:** M · **Depends on:** 17.1
- **Goal:** spec §3: campo `approval` (proposed/approved/deprecated) con migrazione da `status`; `stage` derivato (draft, planned, in development, ready, verified/failing); mostrato da show/list/indice.

### 17.4 - Validazione solo sugli use case pronti

- **Status:** `open` · **Short:** Validazione solo se pronti · **Size:** M · **Depends on:** 17.3, T069
- **Goal:** spec §5 primi tre punti: `use-cases validate` rifiuta se non pronto (salvo `--force` registrato); le campagne eseguono solo gli use case in ambito e riportano gli altri come "Not ready (N/M)"; punteggio sugli use case in ambito.

### 17.5 - Regressione: rivalidazione e blocco della verifica

- **Status:** `open` · **Short:** Regressione use case · **Size:** M · **Depends on:** 17.3
- **Goal:** spec §5 regressione: un task di uno use case verificato riconsegnato, riaperto o respinto mette lo use case in `revalidation: pending` e in coda (`use-cases queue`); un task non arriva a verified/done con uno use case collegato in `failing`, salvo `--owner-approved`.

### 17.6 - Flusso use-case-first nelle skill

- **Status:** `open` · **Short:** Skill use-case-first · **Size:** S · **Depends on:** 17.2
- **Goal:** spec §4: task-pipeline e orchestration-workflow (dai template, rigenerati, anche la skill legata di kilo-mcp) descrivono i quattro passi; `use-cases search` per trovare gli use case collegati.

### 17.7 - Interfaccia: stadi, collegamenti, coda di rivalidazione

- **Status:** `open` · **Short:** UI use case e task · **Size:** M · **Depends on:** 17.3, 17.5
- **Goal:** UI web ed estensione VS Code: badge di stadio e approvazione, task collegati e use case di un task, filtro per use case, coda di rivalidazione; il proprietario la valida usandola.

### 17.8 - Applicazione ai registri esistenti

- **Status:** `open` · **Short:** Migrazione dei registri · **Size:** M · **Depends on:** 17.1, 17.3, 17.4
- **Goal:** `adopt-links` e collegamenti mancanti in ai-orchestration (UC001-UC037), ai-swissknife (UC001-UC034) e git-code-rag (con la sua sessione, che valida); spec §7 punto 7 sulla copia di git-code-rag.
