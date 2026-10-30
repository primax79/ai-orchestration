# 19 - Sviluppo multi-macchina: hub, executor su ogni host, console centrale

- **Short:** Sviluppo multi-macchina

> **Derived from:** [`../specs/multi-machine-development-architecture.md`](../specs/multi-machine-development-architecture.md) (bozza 1) **corretta dalla** [`revisione del 2026-10-29`](../specs/multi-machine-development-architecture.review-2026-10-29.md) (Claude, Codex, Gemini), in particolare §10 con le decisioni dell'owner. Dove spec e revisione divergono vale la revisione §10. Note sorgente: N078–N083.

## Decisioni bloccate (owner, 2026-10-29)

- **Un solo scrittore dello stato dei task (l'hub `alf_ubuntu`), run su qualsiasi host.** Executor sul Mac fin dalla v1.
- **Non rallentare i progetti:** opt-in per progetto (`[multi_host] enabled`), campi additivi (spegnere non richiede migrazioni), modalità offline quando l'hub non risponde, flusso manuale di oggi sempre valido, ogni slice utile da sola e provata su un progetto di prova prima di ricerca_auto.
- **Executor = `kilo run` autonomo in screen** (non `--attach` su `kilo serve`). Stato: fork in sola lettura; correzione: cancel + ripresa della sessione.
- **`delivered` lo dichiara l'executor sul proprio branch**, l'hub lo riconosce (`run ack-delivery`) e solo allora vale su main. R6 di `agent-runs-from-ui.md` cambia di conseguenza.
- **Takeover solo dall'owner**, con incremento della generazione del task (fencing).
- **Agganciarsi agli agenti sull'hub:** `ssh kilo@hub -t screen -x <nome>` con chiave dedicata.
- **`kilo remote` escluso** (manda le sessioni al cloud di Kilo). Tunnel ssh per tutto.
- **Fuori da questa iniziativa:** ruoli/interlocutore/mailbox/handoff (dipendono dall'Iniziativa 18 e da T073, Q028 ancora aperta) e console web (dopo la console CLI); restano come 19.14 e 19.15 in attesa.

## Ordine

Slice 0 (19.1–19.3) e slice 1 (19.4–19.8) sono indipendenti dall'hub: valgono anche su una macchina sola. La 19.9 è il gate: una giornata di lavoro reale su un progetto di prova. La slice 2 (19.10–19.13) introduce la coda condivisa tra host.

## Tasks (One Task = One Commit)

### 19.1 - Lookup unico della configurazione di progetto

- **Status:** `in progress` (2026-10-29; Verifica Codex NON OK: vedi tasks/19-multi-machine-development/notes/19.1-verification-codex.md; 2026-10-30; rinviato allo stesso executor su alf_ubuntu con i rilievi) · **Short:** Lookup config unico · **Size:** M · **Kind:** fix · **Depends on:** - · **Use cases:** UC038 · **Repo:** `ai-orchestration/`
- **Goal:** una sola funzione decide dove sta la configurazione di progetto e tutti la usano: oggi `orchestration_config.find_project_config_path` (`.ai-orchestration.local.toml`, poi `~/.config/ai-orchestration/projects/<dir>/orchestration.toml`), `tasks_engine` (`tasks/orchestration.toml`, `<proj>/orchestration.toml`, `tasks/AGENTS.md`: `tasks_engine.py:425`, `:596-685`) e i trigger (`orchestration_triggers.py:305-311`) leggono percorsi diversi. Fissare l'ordine (documentato), mantenere i percorsi legacy in sola lettura con un avviso, correggere `docs/00-QUICKSTART-AND-PLAYBOOK.md:117-149`, `plugins/shared/skills/orchestration-setup/SKILL.md:68,138` (template, non il generato) e `specs/orchestration-config-and-agents-md.md` §3.
- **Verification:** test che per ogni posizione legacy lo stesso valore (es. `extension_fields`, una regola di trigger) viene letto da tutti e tre i sottosistemi; `ai-orch tasks config` e `ai-orch env status` riportano lo stesso percorso; `grep -rn "tasks/orchestration.toml" docs plugins/*/skills/*/SKILL.template.md` non trova istruzioni a scriverci; suite completa verde.

### 19.2 - `ai-orch doctor` di progetto: rilevare il drift

- **Status:** `in progress` (2026-10-30; Verifica Codex NON OK: vedi tasks/19-multi-machine-development/notes/19.2-verification-codex.md; 2026-10-30; rinviato allo stesso executor su alf_ubuntu con i rilievi) · **Short:** Doctor di progetto · **Size:** M · **Kind:** feature · **Depends on:** 19.1 · **Use cases:** UC038 · **Repo:** `ai-orchestration/`
- **Goal:** N078 punti 1, 2, 4. Comando `ai-orch doctor [--project PATH] [--json]` costruito sul doctor di `env` esistente (`orchestration_env.py:410-500`, ack/unack) e sui controlli di `tasks upgrade`: config mancante, workspace non registrato, indice senza marker, AGENTS.md renderizzato vecchio o con blocchi scritti a mano duplicati, campi header di schemi vecchi, skill/config globali di versione diversa da quella del tool. Ogni rilievo ha severità e il comando che lo corregge. Registrare per progetto la versione di convenzione (`convention_version`, file versionato in `tasks/`). Avviso di una riga da ogni comando `ai-orch` lanciato in un progetto con drift (disattivabile).
- **Verification:** fixture con un progetto "stile 2026-10-17" (ricostruito sullo stato descritto in N078) → tutti i rilievi attesi con severità; progetto aggiornato → nessun rilievo; `--json` stabile; il drift di skill globali è rilevato con due versioni installate finte.

### 19.3 - `ai-orch upgrade` di progetto

- **Status:** `in progress` (2026-10-30; Verifica Codex NON OK: vedi tasks/19-multi-machine-development/notes/19.3-verification-codex.md; 2026-10-30; rinviato allo stesso executor su alf_ubuntu con i rilievi) · **Short:** Upgrade di progetto · **Size:** M · **Kind:** feature · **Depends on:** 19.2 · **Use cases:** UC038 · **Repo:** `ai-orchestration/`
- **Goal:** N078 punto 3. `ai-orch upgrade` (preview di default, plan hash, `--apply --expect-hash`) che compone i passi esistenti (`tasks upgrade`, adozione dei marker dell'indice, scrittura della config, registrazione del workspace, re-render di AGENTS.md rimuovendo i duplicati scritti a mano, migrazione dei campi header) e aggiorna `convention_version`. Rifiuta con motivo chiaro se ci sono worktree di executor attivi del progetto.
- **Verification:** sulla fixture di 19.2: preview → apply → `ai-orch doctor` senza rilievi e `tasks validate` senza errori; secondo apply = nessuna modifica; con un worktree attivo il comando rifiuta; i blocchi di AGENTS.md fuori dai marker restano byte per byte.

### 19.4 - Identità dell'host

- **Status:** `in progress` (2026-10-29; kilo (gemini-4-argon) in screen su alf_ubuntu, worktree ../.worktrees/ai-orchestration/19.4-host-identity) · **Short:** Identità dell'host · **Size:** S · **Kind:** feature · **Depends on:** - · **Use cases:** UC039, UC040 · **Repo:** `ai-orchestration/`
- **Goal:** id canonico dell'host (`[host] id` nella config globale, fallback hostname normalizzato) e tabella `[hosts.<id>]` (ssh target, utente per gli agenti, ruolo `hub`/`client`). L'id va in `run.json`, negli eventi, nei record di sessione. Nuovo campo task opzionale `host` con valore validato (id dichiarati), anche nei microtask; niente `run-ref` (si usa `run-id`).
- **Verification:** test unitari su risoluzione dell'id e validazione; un run nuovo ha `host`; `tasks validate` rifiuta un `host` non dichiarato; run e task esistenti senza `host` restano validi.

### 19.5 - `reconcile()` consapevole dell'host

- **Status:** `open` · **Short:** Reconcile per host · **Size:** S · **Kind:** fix · **Depends on:** 19.4 · **Use cases:** UC039 · **Repo:** `ai-orchestration/`
- **Goal:** `reconcile()` (`orchestration_runs.py:2879-2945`) agisce solo sui run con `host` uguale all'host corrente: mai `lost`, mai `kill_process_group` sui run di altri host; per quelli espone l'ultimo heartbeat e la sua età. I run vecchi senza `host` sono considerati locali.
- **Verification:** test con un `run.json` di un altro host e pid inesistente: resta nel suo stato, nessun kill, nessun evento `run.lost`; stesso caso con host locale → `lost` come oggi.

### 19.6 - Backend di run `screen`

- **Status:** `open` · **Short:** Backend screen · **Size:** L · **Kind:** feature · **Depends on:** 19.4 · **Use cases:** UC039 · **Repo:** `ai-orchestration/`
- **Goal:** backend selezionabile per progetto/tool accanto al supervisor attuale (che resta il default): sessione `agent-<project>-<task>` (verify: `verify-<project>-<task>`), log con `screen -L` in `.ai-orchestration/runs/<run_id>/session.log`, file di stato scritto in uscita (exit code, fine, puntatore al Final Report), liveness = sessione screen viva + file di stato. Il nome della sessione va in `run.json`. Correggere anche `run preview`, che riporta un percorso di worktree diverso da quello creato (`orchestration_runs.py:4133`, `:3542` vs `:4789`).
- **Verification:** run reale con un tool finto (script che dorme e scrive un commit) in screen: `run list` lo vede vivo, `screen -ls` mostra il nome atteso, alla fine il run è `completed` con exit code; uccidendo la sessione il run diventa `lost`; `run cancel` chiude la sessione; supervisor setsid invariato (test esistenti verdi).

### 19.7 - Preflight eseguibile e timeout per progetto

- **Status:** `in progress` (2026-10-30; Verifica Codex NON OK: vedi tasks/19-multi-machine-development/notes/19.7-verification-codex.md; 2026-10-30; rinviato allo stesso executor su alf_ubuntu con i rilievi) · **Short:** Preflight per host · **Size:** M · **Kind:** feature · **Depends on:** 19.1 · **Use cases:** UC040 · **Repo:** `ai-orchestration/`
- **Goal:** `[project.preflight]` (strumenti con versione minima, porte libere, servizi attivi, spazio disco) eseguito sull'host di destinazione prima di ogni `run start`; se fallisce il dispatch è bloccato con il motivo (caso reale: T205 di ricerca_auto senza `bun`). Timeout dei comandi per progetto, passati all'executor nel prompt. `verification_checks` diventa eseguibile con `ai-orch verify-checks`.
- **Verification:** test con un preflight che chiede un binario inesistente → `run start` rifiuta con il nome del binario; preflight ok → run parte; timeout presente nel prompt generato.

### 19.8 - Console CLI multi-host: `status` e `attach`

- **Status:** `open` · **Short:** Console CLI multi-host · **Size:** M · **Kind:** feature · **Depends on:** 19.4, 19.5, 19.6 · **Use cases:** UC039 · **Repo:** `ai-orchestration/`
- **Goal:** `ai-orch console status [--all-hosts] [--json]`: per ogni host dichiarato esegue `ssh <host> ai-orch … --json` (nessun demone), aggrega progetti, task per stato e host, run, domande aperte, consegne da verificare; un host irraggiungibile è mostrato come tale e non blocca gli altri; timeout per host. `ai-orch console attach <run|task>`: risolve host e nome sessione dal run e apre `ssh -t <target> screen -x <nome>` (sull'hub con l'utente agenti). Host e nomi risolti dal codice, mai interpolati da input libero.
- **Verification:** test con un `ssh` finto (script nel PATH) che simula due host, uno giù; prova manuale reale Mac → alf_ubuntu documentata in PROGRESS dell'iniziativa (output di `status` e un `attach` con detach che lascia il run vivo).

### 19.9 - Gate: giornata di lavoro reale su un progetto di prova

- **Status:** `open` · **Short:** Gate progetto di prova · **Size:** M · **Kind:** investigation · **Depends on:** 19.6, 19.7, 19.8 · **Use cases:** UC039 · **Repo:** `ai-orchestration/`
- **Goal:** un progetto di prova (non ricerca_auto) con alcuni task reali eseguiti da executor Kilo in screen su alf_ubuntu e sul Mac, seguiti solo da `console status/attach`. Annotare ogni attrito come nota inbox. Esito: go / correzioni prima della slice 2.
- **Verification:** report in `tasks/19-multi-machine-development/notes/19.9-gate.md` con i run eseguiti, i problemi e il verdetto; l'owner approva il passaggio alla slice 2.

### 19.10 - L'hub committa e pusha le proprie transizioni

- **Status:** `open` · **Short:** Hub scrive e pusha · **Size:** M · **Kind:** feature · **Depends on:** 19.4, 19.9 · **Use cases:** UC040 · **Repo:** `ai-orchestration/`
- **Goal:** con `[multi_host] enabled` e l'host di ruolo `hub`, ogni mutazione del motore sui task (transition, claim, ack) viene committata e pushata al repository di riferimento dentro lo stesso lock; push rifiutato → fetch, ri-applicazione o rifiuto chiaro. Sui client le stesse mutazioni vengono inoltrate all'hub (vedi 19.12). Progetti senza `multi_host` invariati.
- **Verification:** test con un repo bare locale come origin: una transizione produce un commit pushato con messaggio standard; due mutazioni concorrenti non perdono nulla; con `multi_host` spento nessun commit.

### 19.11 - Claim con generazione e `run ack-delivery`

- **Status:** `open` · **Short:** Claim e ack-delivery · **Size:** L · **Kind:** feature · **Depends on:** 19.10 · **Use cases:** UC040 · **Repo:** `ai-orchestration/`
- **Goal:** `ai-orch tasks claim <id> --host --run --expect-task-hash` (`open → in progress` con `host` e generazione per task) eseguito sull'hub sotto il suo lock; `run start` usa il claim invece della transizione interna, e il claim avviene prima della creazione del worktree. L'executor scrive `state: delivered` sul proprio branch; `ai-orch run ack-delivery <run_id> --generation <g>` legge l'header dal branch pushato, controlla generazione, commit dopo la base, Final Report, scrive `delivered` su main ed emette `run.delivered`. Aggiornare R6 in `specs/agent-runs-from-ui.md`, il contratto dell'executor e `mark-delivered` (alias o deprecato).
- **Verification:** test: claim concorrente dello stesso task → uno solo vince; ack con generazione vecchia → rifiutato; executor che non dichiara `delivered` → task resta `in progress`, run `failed`; merge del branch su main senza conflitti sull'header; la regola `verify-on-delivery` scatta.

### 19.12 - Run sul client: claim remoto, heartbeat, modalità offline

- **Status:** `open` · **Short:** Run sul client · **Size:** L · **Kind:** feature · **Depends on:** 19.6, 19.11 · **Use cases:** UC040 · **Repo:** `ai-orchestration/`
- **Goal:** su un host `client`, `run start` chiama `ssh <hub> ai-orch tasks claim …`, fa pull, crea il worktree e avvia l'executor in screen; il supervisor manda heartbeat all'hub (`run heartbeat`: stato, ultima riga di log, costo, exit) e alla fine pusha il branch e chiama `run ack-delivery` sull'hub. `run start --offline` (o automatico con hub irraggiungibile e conferma) fa un claim locale (`claim: offline`) e parte subito; al ritorno dell'hub una riconciliazione pusha il claim o, se l'hub ha dato il task ad altri, si ferma e chiede all'owner.
- **Verification:** test con hub simulato (repo bare + `ssh` finto): flusso completo client → hub; heartbeat visibili in `console status` sull'hub; scenario offline → riconnessione senza conflitto e con conflitto (owner interpellato, nulla sovrascritto).

### 19.13 - Takeover dell'owner con fencing

- **Status:** `open` · **Short:** Takeover con fencing · **Size:** M · **Kind:** feature · **Depends on:** 19.11 · **Use cases:** UC040 · **Repo:** `ai-orchestration/`
- **Goal:** `ai-orch tasks takeover <id> --host <h> --force` (solo owner, conferma esplicita) incrementa la generazione e riassegna; il vecchio run che si riconnette riceve il rifiuto alla consegna e lo segnala. Nessun takeover automatico (Q028 aperta).
- **Verification:** test: run A in corso, takeover verso B, ack di A rifiutato, ack di B accettato; evento di takeover con attore `owner (via console@host)`.

### 19.16 - Registro dei progetti sull'hub

- **Status:** `open` · **Short:** Registro progetti hub · **Size:** M · **Kind:** feature · **Depends on:** 19.4 · **Use cases:** UC039 · **Repo:** `ai-orchestration/`
- **Goal:** N079. Il registro attuale (`orchestration_registry.py`, SQLite per macchina) identifica i workspace con `canonical_path`, `device`, `inode` e non si può condividere. Registro dei progetti sull'hub con identità portabile (uuid), percorsi per host, host primario, repository di riferimento e mirror, `convention_version`; il SQLite locale diventa una cache. Assorbire `~/works/MIGRATION_REGISTRY.json` (importazione una tantum, nessun secondo registro). Coordinarsi con la risposta Q026=A (scoperta dei workspace non registrati) e con T073.
- **Verification:** importazione del file di migrazione su una copia; lo stesso progetto ha lo stesso uuid sul Mac e sull'hub; `console status` elenca i progetti dal registro dell'hub; il registro locale resta utilizzabile con l'hub irraggiungibile.

### 19.17 - Allineamento automatico dei checkout dopo un push

- **Status:** `open` · **Short:** Sync automatico checkout · **Size:** M · **Kind:** feature · **Depends on:** 19.4, 19.16 · **Use cases:** UC040 · **Repo:** `ai-orchestration/`
- **Goal:** richiesta dell'owner (2026-10-29): dopo un push, i checkout degli altri host si aggiornano da soli, senza `git pull` a mano. Nessun webhook da GitHub/Gitea verso l'hub (richiederebbe un endpoint pubblico). Tre meccanismi, in ordine: (1) per i repository di riferimento sull'hub (bare), un hook `post-receive` che fa fast-forward dei checkout registrati sull'hub e manda il mirror su Gitea; (2) per i repository con origin esterno (es. GitHub), un timer `systemd --user` sull'hub (e `launchd` sul Mac) che fa `fetch` + solo fast-forward ogni N minuti; (3) un hook `post-push` lato client facoltativo che avvisa subito l'hub via ssh. In tutti i casi: mai toccare checkout sporchi, in avanti o divergenti (li segnala a `doctor`), mai worktree di executor attivi; elenco dei checkout dal registro (19.16).
- **Verification:** test con repo bare locale: push → checkout pulito aggiornato, checkout sporco lasciato com'è e segnalato; timer simulato con fetch da un origin che è avanzato; nessuna modifica a worktree attivi.

### 19.14 - Riconciliare ruoli, interlocutore e handoff con Iniziativa 18 e T073

- **Status:** `open` · **Short:** Ruoli e handoff · **Size:** M · **Kind:** investigation · **Depends on:** 19.9 · **Repo:** `ai-orchestration/`
- **Goal:** prima di qualunque codice sui ruoli: chiave `(workspace_uuid, project_uuid | "_workspace", role)` dell'Iniziativa 18, ruolo interlocutore nella matrice di autorità di T073 (e se può toccare codice di prodotto), mailbox (16.7/16.8) senza quarantena per l'interlocutore, documento di handoff basato su `pending_handoff`. Esito: aggiornamento delle spec e task nuovi. Revisione §4–§5 e B4.
- **Verification:** spec aggiornate e revisionate da un secondo motore; task creati e registrati.

### 19.15 - Console web multi-host

- **Status:** `open` · **Short:** Console web multi-host · **Size:** L · **Kind:** feature · **Depends on:** 19.8, 19.12 · **Use cases:** UC039 · **Repo:** `ai-orchestration-ui/`
- **Goal:** da dettagliare dopo 19.9 e 19.14: estendere la vista Fleet (Iniziativa 18, 18.7–18.8) a più host, azioni con conferma sul client, terminale embedded solo dopo aver risolto B5 della revisione (token leggibile dagli agenti, CSP, allowlist Host).
- **Verification:** da definire quando il task viene dettagliato.
