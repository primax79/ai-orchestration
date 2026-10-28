# 16 - Broker di orchestrazione: un server MCP per utente, workspace, progetti, posta

- **Short:** Broker di orchestrazione

> **Derived from:** [`../specs/orchestration-broker-mcp.md`](../specs/orchestration-broker-mcp.md) (bozza 4, ambito v1, decisioni dell'owner Q-a avvio on-demand e Q-c annidamento, regola di collocazione). Leggere prima la specifica; questo piano non la ripete. Revisioni: `../_reviews/2026-10-18-*`. Le correzioni preliminari sul motore attuale sono i task emergenti T026, T027, T028 (specifica §8 passo 1).

## Tasks (One Task = One Commit)

### 16.5 - Tool MCP del broker: letture, poi scritture deterministiche

- **Status:** `bounced` (2026-10-21; Validazione NON OK: manca 'ai-orch mcp --local' (tool in-process) promesso dal Goal; codici di errore e campo project fuori specifica. Correzione in T045 (Follow-up validazione broker).) · **Short:** Tool MCP del broker · **Size:** L · **Depends on:** 16.1, 16.2, 16.4 · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/`
- **Goal:** specifica §3: il broker dal backend della UI; tool di lettura; scritture deterministiche applicate direttamente con `expect_hash` opzionale, `preview: true`, chiavi di idempotenza; `confirm_token` solo per azioni distruttive o rivolte all'owner; binding lazy della console con workspace/progetto esplicito (mai la cwd del broker); `ai-orch mcp --local`.

### 16.7 - Worker orchestratori nel broker; ripristino; ticket orchestrator.ask

- **Status:** `open` · **Short:** Orchestratori nel broker · **Size:** L · **Depends on:** 16.5, T027, T028 · **Repo:** `ai-orchestration/`
- **Goal:** specifica §2 ripristino e §4: worker serializzati per-workspace nel broker, processi figli distaccati con pid/sessione/log persistiti, ri-aggancio al riavvio, `outcome_unknown` per mutazioni interrotte, `broker stop --drain`, valutazione dei trigger spostata all'interno (vecchio lock del demone mantenuto), `orchestrator.ensure`, ticket `orchestrator.ask` durevoli.

### 16.8 - Posta: orchestratori di workspace, poi console; UI

- **Status:** `open` · **Short:** Posta di workspace · **Size:** L · **Depends on:** 16.7 · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/` + `vscode-ai-orchestration/`
- **Goal:** specifica §5–§6: posta agli orchestratori di workspace con quarantena di soli metadati e accettazione dell'owner, policy e limiti, risposte automatiche su rifiuto/scadenza, `mail.fetch_ref`; poi caselle di posta delle console (lease, uuid+secret, nomi univoci, `console_gone`); vista posta nella UI; parità VS Code.

## Closed

### 16.1 - Spike sui client MCP: broker minimale e shim stdio usati da Claude Code, Kilo e Codex

- **Status:** `done` (2026-10-21; Verificato da d4science-python-library-2e) · **Short:** Spike client MCP · **Size:** M · **Kind:** investigation · **Depends on:** - · **Repo:** `ai-orchestration/`
- **Goal:** il gate del passo 2 in specifica §8. Un broker prototipale usa e getta (`ai-orch broker serve`, streamable HTTP su localhost con il token della UI) e uno shim stdio (`ai-orch mcp`, `initialize` immediato, `broker.launch.lock`, file di readiness) che espongono due tool di lettura (`whoami`, `tasks.list` per un percorso di progetto esplicito) e un tool lento (`debug.sleep`, per il comportamento sulle chiamate lunghe).
- **Verification:** solo con configurazioni client ISOLATE (mai i veri `~/.claude`, `~/.kilo`, `~/.codex`, `~/.config/kilo`): ciascuno tra Claude Code, Kilo e Codex elenca e invoca i tool; due shim avviati contemporaneamente lanciano un solo broker; broker terminato e riavviato a metà sessione → il client recupera oppure la modalità di fallimento viene registrata; un avviso accodato al contenuto testuale è visibile al modello. Report in `tasks/16-orchestration-broker/notes/16.1-client-spike.md` con verdetto go / amend per ciascun client.

### 16.3 - Registro: uuid/slug del workspace, progetti espliciti, annidamento, discover

- **Status:** `done` (2026-10-21; Verificato da d4science-python-library-2e) · **Short:** Registro workspace e progetti · **Size:** M · **Depends on:** 16.2 · **Repo:** `ai-orchestration/`
- **Goal:** specifica §1–§2: `[workspace] uuid, id`, `[[workspace.projects]]`, la regola di annidamento (il workspace registrato più vicino possiede gli alberi; i sub-workspace sono elencati in sola lettura), registro in SQLite sotto la directory di configurazione globale (rispetta `AI_ORCHESTRATION_CONFIG`), spostamento del percorso con conferma, controlli symlink/inode, `projects discover` che si limita a proporre le voci.

### 16.9 - Interfaccia: vista progetto e vista workspace comune

- **Status:** `done` (2026-10-21; Verificato da d4science-python-library-2e) · **Short:** Viste progetto e workspace · **Size:** L · **Depends on:** 16.4 · **Repo:** `ai-orchestration-ui/` + `vscode-ai-orchestration/`
- **Goal:** specifica §7b: selettore di progetto e vista progetto (le viste attuali, id semplici); vista workspace comune con id qualificati, colonna/filtri/raggruppamento per progetto, task di coordinamento che si espandono nei task di progetto coordinati, domande/inbox/esecuzioni/posta a livello di workspace con colonna progetto, scritture instradate al progetto dell'elemento; vista memorizzata per finestra; deep link `workspace:project/ID`; infine panoramica in sola lettura di tutti i workspace. VS Code: le stesse viste tramite il bridge e un selettore di progetto nelle viste ad albero.
- **Detail spec (2026-10-20):** [`../specs/ui-multi-project.md`](../specs/ui-multi-project.md); non attende più 16.5 (la UI invoca direttamente la CLI del motore). Parti: 16.9a backend (consegnato 2026-10-20, ai-orchestration-ui b4efea0), 16.9b web UI (consegnato 2026-10-20, ai-orchestration-ui 2fe1c72; la vista comune carica i task attivi, quelli chiusi su richiesta, in ogni pagina), 16.9c VS Code (consegnato 2026-10-20, vscode-ai-orchestration 0.6.0).

### 16.2 - Lock condivisi su disco, CAS e chiavi di idempotenza nel motore

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Lock condivisi e idempotenza · **Size:** M · **Depends on:** T026 · **Repo:** `ai-orchestration/`
- **Goal:** specifica §2 "Locks are on disk": ogni mutazione dei task (CLI o broker) sotto `tasks/.ai-orch.lock` con CAS sull'hash del file; chiavi di idempotenza con risultati terminali memorizzati per le chiamate mutanti; singleton del broker (`broker.lock`) e regola di instradamento della CLI (lock acquisito → tramite il broker oppure "busy"; mai una stima basata su timeout HTTP); CAS `config_lock` per setup/ensure (C7).

### 16.4 - QualifiedTaskRef, link coordinates: e regola di collocazione

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Riferimenti qualificati e coordinamento · **Size:** M · **Depends on:** 16.3 · **Repo:** `ai-orchestration/`
- **Goal:** un unico parser/canonicalizzatore per `[workspace:][project/]ID` (i prefissi malformati sono errori); `coordinates:` sui task dell'albero di workspace risolto in sola lettura verso i task di progetto; avvisi di collocazione in `validate`; `tasks move ID --to-project P` con anteprima e puntatore lasciato nella posizione originale; `depends-on` su disco invariato.

### 16.6 - Passaggio delle skill al broker

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Le skill usano il broker · **Size:** M · **Depends on:** 16.5 · **Repo:** `ai-orchestration/` + `kilo-mcp/`
- **Goal:** specifica §7: i template generici e i binding istruiscono le sessioni a usare i tool del broker, `orchestrator.ask` per la formalizzazione e gli aggiornamenti di stato, la regola di citazione con riferimenti qualificati, `unread_mail`; istruzioni CLI mantenute come fallback; registrazione MCP dello shim offerta dal Doctor/setup (anteprima, mai silenziosa), con percorso del comando privo di versione affinché le registrazioni sopravvivano agli aggiornamenti dei plugin.
- **Priority (owner, 2026-10-21):** prossimo elemento principale, insieme a T032 (scritture CLI tramite broker). Risponde al primo ciclo di feedback: percorsi della cache dei plugin con versione e copie vendored obsolete del motore (inbox N003, N010), e fornisce a ogni sessione lo stesso motore. Gli elementi di feedback sul motore (T035, T036, T041) atterrano nel motore, così sia i tool del broker sia la CLI ne beneficiano.
