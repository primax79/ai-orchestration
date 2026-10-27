# 11 - Gerarchia di task di prima classe (N livelli)

- **Short:** Gerarchia dei task

> **Derived from:** [`../specs/subtasks.md`](../../specs/subtasks.md). Viene **prima** del lavoro sul motore dell'iniziativa 10: 10.1 costruisce `tasks graph` sul parser dei nodi figli di 11.1. Ordine delle corsie: vedere `../06-control-plane-safety/plan.md`.

## Tasks (One Task = One Commit)

## Closed

### 11.1 - Motore: parser ricorsivo dei nodi, ereditarietà, transizioni solo sulle foglie, stato derivato dei contenitori, dipendenze sui contenitori, comandi strutturali (`child add`, `expand`, `collapse`, `reopen`; nessun `move`, specifica S1)

- **Status:** `done` (2026-10-17; claude; unito in main) · **Short:** Parser ricorsivo dei nodi · **Size:** L · **Profile:** `deep-reasoning` · **Depends on:** 09.1 (stesso file) · **Note:** il task del motore più grande finora; revisionare in due passaggi (prima parser e stato, poi comandi strutturali) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md`, `tasks/specs/blocking-questions.md` (`blocks` accetta id figli)
- **Goal:** Specifica §1–§3 e §5:
  - le tre regole a qualsiasi profondità;
  - `transition` su un blocco riscrive solo quel blocco, lasciando il resto identico byte per byte;
  - le transizioni sui contenitori vengono rifiutate;
  - le celle di stato delle Iniziative vengono generate;
  - le domande possono bloccare qualsiasi nodo.
- **Verification:**
  - Test:
    - parsing alle profondità 1–5 (blocchi più cartelle annidate) e avviso alla profondità 4;
    - punti elenco multi-chiave con `·` ed ereditarietà;
    - una transizione di blocco lascia il resto del file identico byte per byte;
    - ogni regola di stato derivato;
    - la dipendenza da un contenitore si espande alle sue foglie;
    - dipendenze ereditate dagli antenati;
    - i cicli attraverso gli antenati vengono rifiutati;
    - `child add` trasforma una foglia in un contenitore e viene rifiutato quando la foglia è in lavorazione;
    - ciclo completo `expand`/`collapse`;
    - ogni regola di stato derivato S5, la grammatica dei punti elenco S7 su fixture copiate dai piani reali, allocazione S8 attraverso i figli archiviati, hash delle operazioni S10 ed ereditarietà S11 per campo;
    - una domanda che blocca `07.4`.
  - Dal vivo: `tasks list --json` su questo repository mostra ogni figlio di 06–11 con il suo stato reale.
  - Dal vivo: `sync-index --check` mostra le celle generate dello stato delle iniziative; il diff di anteprima viene esaminato prima dell'applicazione.

### 11.2 - Esecuzioni sui task figli

- **Status:** `done` (2026-10-17) · **Short:** Esecuzioni sui task figli · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1, 07.4 · **Repo:** `ai-orchestration/`
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`, `tasks/specs/agent-runs-from-ui.md` (nota sull'ambito in §1)
- **Goal:** Specifica §3: rimuovere la restrizione ai soli `T###` della specifica 07 §1. I prompt di esecuzione includono il contesto genitore (intestazione del `plan.md` dell'iniziativa o `README`/`CONTEXT` della cartella) più il blocco figlio.
- **Verification:** Test con l'agente stub: un'esecuzione execute su `NN.T` porta il blocco a `in progress`; mark-delivered e verify sul blocco. Tutti gli unit test passano.

### 11.5 - Normalizzazione dei piani legacy: rilevamento, modalità di esecuzione `normalize`, preview/apply

- **Status:** `done` (2026-10-17) · **Short:** Normalizzazione piani legacy · **Profile:** `deep-reasoning` · **Depends on:** 11.1, 07.4 · **Repo:** `ai-orchestration/` (+ `ai-orchestration-ui/` per la parte UI, dopo 11.3)
- **Origin:** owner, 2026-10-17, su `ricerca_auto`: tutti gli 11 piani delle iniziative sono a formato libero (punti elenco `- **T1 — …**`, sezioni `### 3.1 …`, `### 01.1 — …` con trattino lungo), quindi il motore non analizza alcun blocco task e mostra ciascuna iniziativa come un'unica scheda sintetica `INIT-NN` il cui dettaglio fallisce ("Task INIT-11 file not found"). "La nostra skill non dovrebbe normalizzare e sistemare i task?"
- **Goal:**
  - **Rilevamento (motore, deterministico):** `tasks validate` avvisa, per ciascun piano, "no canonical task blocks; found N candidate legacy tasks in plan.md", e `tasks list` analizza in modo pulito i task in tabella e i task nei titoli con separatori trattino lungo/medio.
  - **`tasks upgrade`** aggiorna gli alberi dei task meno recenti, predispone le directory standard e normalizza `tasks/AGENTS.md`.
  - **UI e Webview:** `getTaskDetail` renderizza il contenuto del piano per `INIT-NN` e i task basati su tabella senza sollevare 404. Tutti gli unit test passano.

### 11.6 - Follow-up della revisione di 11.1: applicazione di S10, `reopen` completo, figli di `T###`, test CLI

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Follow-up revisione gerarchia · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1 · **Repo:** `ai-orchestration/`
- **Origin:** revisione di 11.1 (2026-10-17), elementi non ancora coperti dal motore unito.
- **Goal:**
  - S10: `--expect-plan-hash` obbligatorio in fase di applicazione per `child add`, `expand`, `collapse`, `reopen` (attualmente opzionale);
  - `reopen` scrive `--reason` e ripristina gli antenati (S2) per i nodi ancora in posizione (i casi `done/` e `## Closed` restano con 11.4);
  - `child add` / `set-labels` sui nodi file e cartella (`T014.1`), e `tasks new --from-note --parent ID` (specifica §3);
  - `set-deps` su un file emergente riscrive solo la relativa riga di intestazione;
  - `tasks/specs/blocking-questions.md`: `blocks` accetta id figli;
  - test a livello CLI per `child add`, `expand`, `collapse`, `reopen`, `set-deps`, `set-labels`, `expand`/`collapse` a profondità > 2, e le celle generate dello stato delle Iniziative in `sync-index`.
- **Verification:** i test sopra indicati; `validate` pulito su questo repository e su `ricerca_auto` (sola lettura).

### 11.3 - UI: albero comprimibile a qualsiasi profondità, dettaglio del nodo con ereditarietà, aggiunta figlio, espansione, spostamento, breadcrumb

- **Status:** `done` (2026-10-21; Verificato da d4science-python-library-2e) · **Short:** UI albero comprimibile · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 11.1, 06.8 (corsia frontend) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `frontend/src/**`
- **Goal:** Specifica §4.
- **Verification:** Dal vivo con Playwright su una copia temporanea di `tasks/` di questo repository: l'albero mostra 06–11 con barre di avanzamento; la transizione di un figlio aggiorna il relativo blocco e il riepilogo padre; "Add subtask" su un task a cartella crea `T###.1`.

### 11.4 - Motore: collocazione separata dei chiusi a ogni livello (`tasks ship`, sezione `## Closed` per i blocchi, riscrittura dei link, `tasks archive`; le domande restano sul posto secondo S3)

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Collocazione separata chiusi · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1 (stesso file) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `plugins/architect-side/skills/task-pipeline/SKILL.md` (passo "Ship"), `tasks/specs/blocking-questions.md` (posizione delle domande chiuse)
- **Goal:** Specifica §6.
- **Verification:**
  - Test:
    - la chiusura di un blocco foglia lo sposta in `## Closed`, e la sua riapertura lo riporta indietro;
    - la chiusura di un figlio a cartella lo sposta in `done/` sotto il proprio genitore;
    - un'iniziativa la cui ultima foglia viene chiusa è completata con `tasks ship`, e i link nelle specifiche e nell'indice vengono riscritti;
    - le domande non si spostano mai (S3, specifica 12 E11);
    - `tasks archive --dry-run` su una fixture con elementi fuori posto mostra il piano e non scrive nulla;
    - ogni link Markdown relativo in `tasks/**` continua a risolversi dopo ciascuna operazione (un controllore di link fa parte del test).
  - Dal vivo: `tasks archive --dry-run` su questo repository segnala che non c'è nulla da fare.
