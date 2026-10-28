# 10 - Timeline astratta: dipendenze e priorità

- **Short:** Timeline astratta

> **Derived from:** [`../specs/timeline-gantt.md`](../../specs/timeline-gantt.md). Ordine delle corsie: vedere `../06-control-plane-safety/plan.md`.

## Tasks (One Task = One Commit)

## Closed

### 10.1 - Motore: `tasks graph` (colonne, coda pronta, catena più pesante, Mermaid), campo `size`, `tasks set-priority`, `tasks set-size`, `tasks set-deps`, controllo dei cicli

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Motore del grafo task · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 11.1 (parser dei nodi figli; stesso file, corsia `tasks_engine.py`) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md` (il campo di estensione `size`)
- **Goal:** Specifica §2. Aggiungere inoltre `**Size:**` ai task aperti dei piani 06–10, usando queste stime: 06.8 L, 06.9 M, 07.4 L, 07.5 M, 07.6 M, 07.7 L, 07.8 M, 07.9 S, 07.10 S, 08.3 S, 08.4 M, 08.5 S, 08.6 S, 09.1 M, 09.2 M, 09.3 L, 09.4 M, 09.5 M, 09.6 S, 10.1 M, 10.2 L, 10.3 S.
- **Verification:**
  - Test:
    - ogni forma dei punti elenco `NN.T` viene analizzata, con priorità ereditate;
    - le colonne e la coda pronta vengono calcolate correttamente;
    - `set-deps` rifiuta un ciclo e lo nomina;
    - `set-deps` mantiene il testo libero di un punto elenco `**Depends on:**`;
    - `set-priority` e `set-size` funzionano su `T###` (intestazione) e su `NN.T` (punto elenco creato o aggiornato);
    - la catena più pesante e i totali seguono le dimensioni;
    - un hash obsoleto viene rifiutato;
    - `--dry-run` non scrive nulla.
  - Dal vivo: `tasks graph --json` su questo repository mostra 06–10 in colonne coerenti e `--mermaid` viene renderizzato in VS Code.

### 10.4 - Motore: microtask (categoria `micro`, schema ridotto, `tasks micro`, `tasks promote`, dimensione XS), tipo ed etichette

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Motore dei microtask · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 10.1 (stesso file) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md`, `plugins/architect-side/skills/task-pipeline/SKILL.md` (documentare la forma dei microtask)
- **Goal:** Specifica §5 (tutto tranne le esecuzioni batch e la UI) e parte motore della specifica §6:
  - campi `kind` e `labels` (estensioni dell'intestazione `T###`, punti elenco `NN.T`);
  - `set-kind` e `set-labels`;
  - filtri `--kind`/`--label`;
  - `tasks labels`;
  - validazione.
- **Verification:**
  - Test: il formato delle etichette e l'insieme dei tipi sono validati; `set-labels --add/--remove` completa il ciclo andata e ritorno; i filtri si combinano con AND tra campi diversi e OR all'interno dello stesso campo; un microtask passa la validazione con l'intestazione ridotta e solo `## What`; compare in `tasks graph` con dimensione `XS`; `promote` produce un task completo che passa la validazione e mantiene il proprio id e le dipendenze che puntano ad esso; `tasks micro` alloca gli id in concorrenza senza collisioni.

### 10.6 - Viste del Backlog: "Next up" compatto, selettore di vista separato (Queue, Kanban, Tree, Timeline)

- **Status:** `done` (2026-10-21; Verificato da d4science-python-library-2e) · **Short:** Selettore vista Backlog · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 06.8 (corsia frontend; può girare prima di 10.1 ed essere arricchito una volta atterrati 10.1 e 11.3) · **Repo:** `ai-orchestration-ui/`
- **Origin:** feedback dell'owner (2026-10-17). "Next Up Focus" era poco chiaro ed enorme: elencava ogni `NN.T`, poiché i task di iniziativa ereditavano lo stato dell'iniziativa, e si trovava nella stessa pagina della Kanban.
- **Goal:**
  - La scheda Backlog riceve un selettore di vista: **Queue**, **Kanban**, **Tree** (11.3), **Timeline** (10.2). L'ultima vista scelta viene memorizzata (localStorage).
  - **Queue** = "cosa iniziare dopo": al massimo 5 righe compatte con id, titolo, priorità, dimensione e tipo, più una riga di spiegazione ("tasks marked next-up, or the first ready tasks by priority once the timeline engine lands"). Non ci sono schede.
  - I contatori KPI diventano un'unica striscia compatta.
  - **Kanban (feedback dell'owner, 2026-10-17):**
    - la colonna Done è nascosta per impostazione predefinita, con un pulsante di attivazione/disattivazione ("Show done") il cui stato viene memorizzato;
    - Delivered e Verified condividono una sola colonna: schede Delivered in alto, schede Verified in basso, con un divisore sottile e un sottotitolo per ciascuna;
    - lo stesso vale per il pulsante della colonna Dropped, se presente.
  - Finché non atterra 10.1, Queue usa solo i task emergenti `next-up: yes`, mai `NN.T`; dopo 10.1 usa la `ready_queue`.
- **Verification:** Dal vivo con Playwright su `tasks/` di questo repository: la vista Queue mostra al massimo 5 righe; il cambio di vista mantiene i filtri; a 1000 px ogni vista entra senza scorrimento orizzontale.

### 10.2 - UI: endpoint del grafo e di modifica e scheda Timeline (frecce, coda pronta, modifica di priorità e dipendenze)

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Scheda Timeline · **Size:** L · **Profile:** `bulk-execution` · **Depends on:** 10.1, 06.8 (corsia frontend; può girare prima di 08.4 quando 08.3 è in ritardo) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`, `frontend/src/**`
- **Goal:** Specifica §3. Endpoint: `GET /api/tasks/graph`, e `POST /api/tasks/{id}/priority`, `/size` e `/deps`, ciascuno con una variante `/preview`.
- **Verification:** Dal vivo con il server MCP Playwright su una copia temporanea di `tasks/` di questo repository:
  - le colonne e le frecce sono visibili;
  - la modifica di una priorità riordina la colonna e la coda pronta;
  - la modifica di una dimensione cambia la larghezza della scheda e i totali;
  - l'aggiunta di una dipendenza sposta la scheda di una colonna a destra;
  - un ciclo viene rifiutato nel selettore;
  - la rimozione di una freccia funziona;
  - uno screenshot viene allegato al Final Report.

### 10.3 - VS Code: Timeline nella webview

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Timeline in VS Code · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 10.2, 06.9 (corsia VS Code) · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/cli-client.ts`, `dist-webview/**`
- **Goal:** Specifica §3 "VS Code".
- **Verification:** Dal vivo in un Extension Development Host.

### 10.5 - UI: aggiunta rapida di microtask, pillole XS, "Promote", tipo ed etichette, barra dei filtri condivisa

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** UI dei microtask · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 10.4, 10.2 (corsia frontend) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `frontend/src/**`
- **Goal:** Specifica §5 "Creation" (UI) e la pillola nella timeline, più la UI della specifica §6: icone di tipo, chip delle etichette, barra dei filtri condivisa, editor delle etichette con completamento automatico, raggruppamento per etichetta. Inoltre: nella scheda inbox (09.3), "Convert to microtask" per le note `bug`, una volta atterrato 09.3.
- **Verification:** Dal vivo con Playwright: aggiungere rapidamente un microtask di tipo bug → compare come pillola XS nella coda pronta → Promote → diventa una scheda completa.
