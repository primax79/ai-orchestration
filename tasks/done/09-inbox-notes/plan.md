# 09 - Inbox: note in bozza, report e screenshot, elaborati in task

- **Short:** Note dell'inbox

> **Derived from:** [`../specs/inbox-notes.md`](../../specs/inbox-notes.md). Leggere prima la specifica. Ordine delle corsie: vedere `../06-control-plane-safety/plan.md` ("UI lane order"); i task della 09 confluiscono nelle medesime corsie.

## Tasks (One Task = One Commit)

## Closed

### 09.1 - Motore: cartelle delle note, `ai-orch inbox ...`, `tasks new --from-note`

- **Status:** `done` (2026-10-17) · **Short:** Motore dell'inbox · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 06.10 (lock); gira nella corsia di `tasks_engine.py` dopo 06.10, prima o dopo 08.1 (mai in parallelo ad esso) · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../test_tasks_engine.py`, `bin/ai-orch`, `plugins/architect-side/skills/task-pipeline/SKILL.md` (documentare la forma a cartella delle note sotto "Capture")
- **Goal:** Specifica §2 e §3.
- **Verification:**
  - Test:
    - cicli completi di add / edit / attach (un png accettato; un file di testo con nome png rifiutato dal controllo dei magic byte; un file oltre 10 MB rifiutato) / detach / resolve / discard / reopen;
    - unicità degli id in concorrenza;
    - le note semplici `.md` legacy vengono elencate;
    - `tasks new --from-note` produce un task accettato da `tasks validate`, con `sources` che punta alla nota.

### 09.2 - Backend UI: endpoint dell'inbox con caricamenti autenticati

- **Status:** `done` (2026-10-17) · **Short:** Endpoint dell'inbox · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 09.1, 06.7 (corsia backend) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Specifica §5 "Safety", più endpoint sottili sopra `ai-orch inbox`: list / show / add / edit / attach (multipart, inviato in streaming su file temporaneo, poi `inbox attach`) / detach / resolve / discard / reopen / servizio degli allegati.
- **Verification:**
  - Test: un caricamento senza il token → 401; un caricamento fuori misura viene rifiutato prima di essere letto interamente; un nome con path traversal viene rifiutato; un allegato servito presenta il tipo rilevato tramite sniffing e `nosniff`.

### 09.3 - Frontend: scheda Inbox, editor con incolla e trascinamento di immagini, "Convert to task" manuale

- **Status:** `done` (2026-10-18; claude; verificato e unito; T012 attivo dal riavvio del server kilo-mcp) · **Short:** Scheda Inbox · **Size:** L · **Profile:** `bulk-execution` · **Depends on:** 09.2, 06.8 (corsia frontend) · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Specifica §5, ad eccezione di "Process with…".
- **Verification:**
  - Dal vivo con il server MCP Playwright su un workspace temporaneo:
    - creare una nota;
    - incollare un'immagine (evento `paste` degli appunti simulato con un blob png) → compare la miniatura ed esiste su disco `attachments/01-*.png`;
    - contrassegnarla come Ready;
    - Convert to task → file `T###` creato e valido;
    - Mark processed → la cartella si trova in `analyzed/` con `produced` impostato.

### 09.7 - Motore: allegati generici (testo, PDF), tipo `feature`, allegati dei task, la conversione copia gli allegati

- **Status:** `done` (2026-10-17; claude; unito) · **Short:** Allegati generici · **Profile:** `deep-reasoning` · **Depends on:** 09.1 · **Repo:** `ai-orchestration/`
- **Origin:** richiesta dell'owner (2026-10-17): "come faccio a aprire una nuova feature/bug … servirebbe gestione allegati".
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py`, il `SKILL.md` di task-pipeline (documentare gli allegati).
- **Goal:** Specifica §7, lato motore: le classi di tipo e i controlli, `inbox attach` che le accetta, `kind: feature`, `tasks attach|detach`, `tasks new --from-note` che copia gli allegati riscrivendo i riferimenti, JSON di `tasks list`/`show` che espone `attachments: [{name, class, size}]` per task e note.
- **Verification:** test per ciascuna classe (accettati e rifiutati: un `.png` che in realtà è testo, un `.log` con un byte NUL, un PDF falso), il limite di 30 file, nomi con path traversal, l'hash del bundle del task che cambia quando si allega un file, la conversione che copia gli allegati e riscrive i link; intera suite del motore verde.

### 09.4 - Triage tramite agente: modalità di esecuzione `triage`, revisione della proposta, accettazione

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Triage tramite agente · **Size:** M · **Profile:** `deep-reasoning` · **Depends on:** 09.1, 07.4, 07.10 (domande) · **Repo:** `ai-orchestration/` (+ UI in 09.5)
- **Focus files:** `scripts/orchestration_runs.py`, `scripts/test_orchestration_runs.py`
- **Goal:** Specifica §4 "By an agent":
  - la modalità `triage`, con il relativo prompt e il passaggio delle immagini specifico per-tool;
  - una policy di permessi di sola lettura;
  - il parsing del blocco `ai-orch-triage` in una proposta memorizzata;
  - `run accept-triage RUN_ID [--only ids] --expect-note-hash H`, che crea i task e risolve la nota.
- **Verification:**
  - Test con l'agente stub.
  - Dal vivo con un tool reale su una nota con screenshot: la proposta fa riferimento a ciò che è visibile nell'immagine.

### 09.5 - Frontend: "Process with…" e revisione della proposta

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Revisione Process-with · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 09.3, 09.4, 07.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `backend/server.py` (endpoint di accettazione), `frontend/dist/**`
- **Goal:** Flusso di revisione della specifica §4 nella UI.
- **Verification:** Dal vivo: elaborare una nota con l'agente stub, modificare un task proposto, rifiutarne un altro, accettare → esiste solo quello accettato.

### 09.6 - VS Code: parità della scheda inbox (incolla e caricamento tramite postMessage)

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Parità inbox VS Code · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 09.3, 06.9 (corsia VS Code) · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/dashboard-panel.ts`, `src/cli-client.ts`, `dist-webview/**`
- **Goal:** Specifica §5 "VS Code".
- **Verification:** Dal vivo in un Extension Development Host: incollare uno screenshot in una nota; il file compare in `attachments/`.

### 09.8 - Backend UI: endpoint per gli allegati dei task e servizio distinto per classe

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Endpoint degli allegati · **Profile:** `bulk-execution` · **Depends on:** 09.7, 09.2 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Specifica §7: `POST/GET/DELETE /api/tasks/{id}/attachments[/{name}]` speculari a quelli dell'inbox; servizio per classe (immagine inline, `text/plain; charset=utf-8`, PDF come allegato), `nosniff` su tutti; il caricamento nell'inbox accetta le nuove classi (decide il motore).
- **Verification:** test per autenticazione, intestazioni di ciascuna classe, rifiuto del path traversal, 409 su hash obsoleto.

### 09.9 - Frontend: allegati per classe nell'editor delle note e nel dettaglio del task

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** UI degli allegati · **Profile:** `bulk-execution` · **Depends on:** 09.3, 09.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`
- **Goal:** UI della specifica §7: miniature, visualizzatore di testo, chip di download PDF; incolla/trascinamento/selettore file anche nel dettaglio del task.
- **Verification:** Playwright su un workspace temporaneo: allegare un `.log` e un `.pdf` a una nota e a un task, aprire il visualizzatore di testo, convertire la nota e verificare gli allegati sul nuovo task.

### 09.10 - Modifica dei task proposti prima di accettare una proposta di triage

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Proposte triage modificabili · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 09.4, 09.5 · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/`
- **Origin:** avvio di 09.4/09.5 (2026-10-17): `run accept-triage` accetta `--only` ma nessuna modifica, mentre la specifica §4 prevede che ciascun task proposto possa essere modificato prima dell'accettazione.
- **Goal:** `run accept-triage ... --edits-file F` (JSON: per indice del task proposto, override di title/category/priority/priority_reason/goal/steps/verification, validati come la proposta); le schede del pannello di revisione diventano modificabili e inviano le modifiche.
- **Verification:** test del motore (i campi modificati finiscono nel task creato, le modifiche non valide vengono rifiutate); dal vivo: modificare un task proposto, accettare, il task presenta il titolo modificato.
- **Progress (2026-10-18):** parte motore unita (`run accept-triage --edits-file`, 117 test di esecuzione); la parte UI (schede della proposta modificabili che inviano le modifiche) attende la corsia frontend dopo 12.6.

### 09.11 - VS Code: handler per gli allegati dei task e il triage (parità con 09.5, 09.8, 09.9)

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Parità allegati VS Code · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 09.6, 09.8, 09.9 · **Repo:** `vscode-ai-orchestration/`
- **Origin:** il test di parità del bridge fallisce dopo 09.5/09.9: `uploadTaskAttachment`, `getTaskAttachment`, `deleteTaskAttachment`, `getTriageProposal`, `acceptTriage` sono privi di handler (2026-10-18).
- **Goal:** i cinque handler, speculari al backend web e agli handler dell'inbox di 09.6 (validazione, pulizia dei file temporanei, contenimento di realpath, content type per classe); `startRun`/`previewRun`/`getRunOptions` accettano un target `note`.
- **Verification:** test di parità e suite dell'estensione verdi; un test per ciascun handler.
