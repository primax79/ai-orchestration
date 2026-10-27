# 12 - Eventi, sessioni di orchestrazione e trigger

- **Short:** Eventi e trigger

> **Derived from:** [`../specs/events-and-triggers.md`](../../specs/events-and-triggers.md). Le modifiche dei §0, §0b e §0c sono normative. Piano riscritto il 2026-10-17 dopo la revisione di Codex: 12.2 è stato suddiviso per file e le dipendenze delle corsie sono esplicite.

## Tasks (One Task = One Commit)

## Closed

### 12.11 - Core: archivio degli eventi (outbox, contatore, manifesto dei chunk, riconciliazione, `events tail`)

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Archivio degli eventi · **Size:** L · **Depends on:** 10.4 (fine corsia `tasks_engine.py`) · **Repo:** `ai-orchestration/` (nuovo modulo `scripts/orchestration_events.py`)
- **Goal:** E1, E13 e lettura in §1.

### 12.12 - Emissione degli eventi da `tasks_engine.py`

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Eventi motore dei task · **Size:** M · **Depends on:** 12.11
- **Goal:** Eventi per task, domande e inbox, tramite l'outbox; il registro di applicazione E11 con `questions apply`.

### 12.13 - Emissione degli eventi da `orchestration_runs.py` ed estrazione della primitiva di invocazione supervisionata

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Eventi motore esecuzioni · **Size:** L · **Depends on:** 12.11, 07.11 (fine corsia esecuzioni)
- **Goal:** E1 ed E4.
- **Also (dalla revisione di 12.11):** `events tail --session S` (specifica §1 riga 128) non era stato implementato in 12.11; aggiungerlo qui, dove gli eventi iniziano a portare la sessione.

### 12.14 - Emissione degli eventi da `orchestration_config.py`; scritture della configurazione sotto lock

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Eventi di configurazione · **Size:** S · **Depends on:** 12.11
- **Goal:** E1 ed E10 `config.changed`.

### 12.3 - Registro delle sessioni e identificatori

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Registro delle sessioni · **Size:** M · **Depends on:** 12.12, 12.13
- **Goal:** §2 ed E10, incluse le modifiche alle intestazioni nelle specifiche 08 e 09.

### 12.4 - Motore dei trigger

- **Status:** `done` (2026-10-18; claude; unito) · **Short:** Motore dei trigger · **Size:** L · **Depends on:** 12.3
- **Goal:** §5, E7 e la policy a capacità ridotta per i turni non presidiati (E3).

### 12.1 - Dati sulla ripresa headless (unito in 07.5)

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Dati ripresa headless · **Size:** M · **Executor:** self · **Depends on:** 07.12
- **Goal:** Il task 07.5 (cattura dal vivo con le vere CLI) copre anche il §0 della specifica ed E8:
  - ripresa da un processo nuovo, dopo un crash, dopo un annullamento, con un id di sessione non valido, con due riprese sovrapposte e dopo un cambio di cwd;
  - campi di utilizzo normalizzati.

  Kilo gira con directory di stato XDG scrivibili usa e getta. Le fixture vanno in `scripts/fixtures/runs/`.

### 12.5 - Ruolo di orchestratore headless (sessioni, coda, turni, successione, limiti)

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Ruolo orchestratore headless · **Size:** L · **Depends on:** 12.1, 12.3, 12.13
- **Goal:** §0, E2, E4, E5, E6, E8 ed E9.

### 12.9 - Configurazione dell'orchestratore: riassegnazione come successione, motore `ai-orch setup` condiviso con la skill `orchestration-setup`

- **Status:** `done with a caveat: validated by the architect, no user yet` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Riassegnazione orchestratore · **Size:** M · **Depends on:** 12.5
- **Goal:** §0b, parte core.

### 12.6 - UI: flussi degli eventi e della coda, area notifiche, pagina Triggers, chip delle sessioni, gruppo "awaiting application"

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** UI flussi di eventi · **Size:** L · **Depends on:** 12.4, corsia frontend dopo 10.5
- **Goal:** §6 ed E12.

### 12.8 - UI: pannello chat dell'orchestratore

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Chat dell'orchestratore · **Size:** L · **Depends on:** 12.5, 12.6
- **Goal:** §0 "Owner chat in the UI" ed E12; conferme delle azioni proposte (E3).

### 12.10 - UI: scheda Orchestrator in Config (titolare attuale, Reassign…, pausa/rotazione) e procedura guidata di primo setup

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Scheda Config orchestratore · **Size:** M · **Depends on:** 12.9, 12.8
- **Goal:** §0b, parte UI.

### 12.7 - VS Code: watcher degli eventi e notifiche

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Watcher eventi VS Code · **Size:** S · **Depends on:** 12.6, corsia VS Code dopo 10.3
- **Goal:** §1 "Reading" (E13) e §6.

> 2026-10-17: i task `12.2a`–`12.2d` sono stati rinumerati in `12.11`–`12.14` (gli id con suffisso letterale non sono id di task validi; validate li segnalava e le loro dipendenze risultavano invisibili).

### 12.15 - VS Code: handler di parità per i tipi di messaggio di 12.6 (sessioni, trigger, azioni proposte, notifiche, in attesa di applicazione)

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Parità 12.6 in VS Code · **Kind:** feature · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 12.6, 12.7 · **Repo:** `vscode-ai-orchestration/`
- **Origin:** revisione di 12.7 (2026-10-18): `scripts/test-bridge-parity.mjs` elenca 18 tipi di messaggio inviati dal frontend di 12.6 che il bridge dell'estensione non gestisce ancora (`pending126Types`).
- **Goal:** la webview della dashboard all'interno di VS Code supporta ogni vista di 12.6 (sessioni, pagina Triggers, azioni proposte, notifiche, domande in attesa di applicazione, coda dell'orchestratore) mappando ciascun messaggio allo stesso comando `ai-orch` eseguito dal backend web; `pending126Types` diventa vuoto.
- **Verification:** `npm test` verde con il controllo di parità che non segnala alcun tipo 12.6 in sospeso; test degli handler per la costruzione dell'argv e per le azioni mutanti che richiedono `--expect-*-hash` laddove previsto dal motore.

### 12.16 - UI: conferma/rifiuto delle azioni proposte dai trigger (collegamento T024) e ordinamento dei turni della chat

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Conferma proposte nella UI · **Kind:** feature · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 12.8 · **Repo:** `ai-orchestration-ui/`
- **Origin:** revisione di 12.8 (2026-10-18): gli endpoint di conferma/rifiuto del backend restituiscono ancora `not-implemented` (scritti prima dell'unione di T024) e il pannello della chat mostra il turno di passaggio di consegne della rotazione sopra i turni precedenti.
- **Goal:** `POST /api/triggers/proposed-actions/{id}/confirm|reject` invocano `ai-orch triggers confirm --expect-hash --actor ui` / `triggers reject --reason`; la pagina Triggers e il pannello della chat ricevono pulsanti Confirm/Reject funzionanti; la conversazione segue un ordine strettamente cronologico.
- **Verification:** test del backend con CLI stub; dal vivo: una proposta `command` in sospeso confermata dalla UI passa a `confirmed`, una rifiutata a `rejected` con la motivazione; dopo una rotazione il turno di passaggio di consegne compare per ultimo.

### 12.17 - VS Code: handler di parità per i tipi di messaggio di 12.8, 12.10 e 12.16 (chat dell'orchestratore, scheda Config e wizard, conferma/rifiuto proposte)

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Parità chat in VS Code · **Kind:** feature · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 12.8, 12.10, 12.16 · **Repo:** `vscode-ai-orchestration/`
- **Origin:** unione di 12.15 (2026-10-18): il controllo di parità segna come in sospeso i nove tipi di messaggio della chat di 12.8 (`pending128Types`); 12.10 e 12.16 ne aggiungeranno altri, e gli handler di conferma/rifiuto di 12.15 rispecchiano ancora i vecchi stub `not-implemented` del backend.
- **Goal:** ogni messaggio inviato dal frontend web dopo 12.8, 12.10 e 12.16 dispone di un handler nel bridge VS Code che costruisce lo stesso argv `ai-orch` del backend; `pending128Types` viene rimosso.
- **Verification:** `npm test` verde senza tipi in sospeso; test degli handler.
