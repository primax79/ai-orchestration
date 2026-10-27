# Analisi di precedenza T018: `orchestration-workflow` vs `kilo-mcp-orchestrator`

**Contesto:** Analisi per Q003 e T018. Confronta la skill generica (`orchestration-workflow`, in questo repository, abbreviata **OW**) e la sua controparte associata (`kilo-mcp-orchestrator` in `kilo-mcp`, abbreviata **KMO**). Valuta se il conflitto di trigger segnalato in `tasks/env-doctor/notes/T016-report.md` rappresenti un'incompatibilità sostanziale e propone regole di precedenza.

---

## 1. Relazione: specializzazione vs contraddizione

KMO è un artefatto generato direttamente a partire da OW tramite `scripts/generate_binding.py` usando `kilo-mcp/bindings/orchestration-workflow.json`. Nella sostanza, KMO è una specializzazione con tool concreti del ciclo di vita indipendente dal protocollo definito in OW.

### Indicazioni sovrapposte (stesse indicazioni, parametrizzate sui tool)
- **Disciplina dei ruoli:** Delegare, non implementare; piccole correzioni di verifica nel worktree consentite, correzioni di logica rimandate indietro (OW:30-48 vs KMO:21-39).
- **Isolamento di Fase 2:** Rischio del comportamento predefinito non isolato; incidente reale di race condition su git; `isolation='worktree'`; risorse condivise sull'host (porte, container); rischio legato a `.git/config` a livello di repository; registrazione di `branch` e `worktree` sul task (OW:56-97 vs KMO:43-62).
- **Delega di Fase 3:** Invio in background non bloccante; passaggio di focus file e skill; scomposizione del lavoro multi-sessione nella pipeline `tasks/` (OW:98-108 vs KMO:63).
- **Verifica di Fase 5 e integrazione 5b:** Non fidarsi mai del solo Final Report; eseguire verifiche di backend/frontend/schema/infrastruttura; build dell'applicazione consumatrice dopo il merge (OW:139-152, 183-188 vs KMO:71-77, 78-83).
- **Chiusura di Fase 6:** Sequenza di checkout esplicita prima del merge; pulizia dei worktree su tutti i percorsi terminali (OW:191-203 vs KMO:85-96).
- **Blocchi metodologici (identici parola per parola):**
  - 7 regole economiche e matrice dei prezzi dei modelli (OW:204-260 vs KMO:98-154).
  - Rigore delle specifiche per richieste di analisi/esplorazione (OW:261-313 vs KMO:155-207).
  - Cattura del lavoro emergente a metà sessione in `tasks/` (OW:314-346 vs KMO:208-240).
  - Domande bloccanti aperte tramite `ai-orch questions ask` (OW:347-365 vs KMO:241-259).

### Coperto solo dalla skill associata (KMO)
- Chiamate ai tool concreti: `kilo_rag_search`, `kilo_implement`, `kilo_task_wait`, `kilo_task_progress`, `kilo_task_cancel`, `kilo_session_revert`, `kilo_log_issue`, `kilo_log_decision` (KMO:42, 63-70, 84).
- Fallback da shell con watcher sul PID dell'host: `while kill -0 <pid>...` (KMO:69).
- Comportamento di registrazione automatica dell'Agent Manager in `.kilo/agent-manager.json` (KMO:262).
- Script diagnostici offline: `diagnose-kilo-tasks.sh`, `kill-kilo-task.sh` (KMO:264-267).

### Coperto solo dalla skill generica (OW) — Omesso in KMO per disallineamento degli override del template
- Modalità di esecuzione nativa a singolo framework rispetto a multi-framework (OW:14-15, 23-28).
- Vincolo sulla frequenza dei controlli di Fase 1: `"once per session or after a dispatch failure"` (OW:54-56).
- Annotazione di consegna sul branch in Fase 4: `"- state: delivered with verification pending: <command>"` (OW:134-138).
- Modalità di verifica di Fase 5 (`independent-session`, `cross-agent`, `panel`, `owner`, `self`) (OW:153-170).
- Tabella decisionale post-verifica di Fase 5: Merge, correzione inline (`<= 5` righe), Bounce (`> 5` righe), fermarsi e chiedere all'utente (OW:172-182).
- Controllo dei rischi di scaffolding: rimozione di configurazioni anomale dell'harness iniettate dai generatori (OW:367-381).
- Tabella unificata del ciclo di vita dei task a 10 stati: `"Track task state as a path, not a label"` (OW:383-407).

### Contraddizioni / Divergenze comportamentali
1. **Polling di completamento vs attesa deterministica in Fase 4:**
   - OW (riga 111): *"Small, well-scoped tasks: a single final-result check is enough."* (Presuppone una notifica asincrona o un controllo a fine esecuzione).
   - KMO (righe 65, 69): *"await completion deterministically with `kilo_task_wait` ... Prefer `kilo_task_wait(task_id=...)` to block until the task completes ... or zero-token OS PID watcher"*.
   - *Impatto:* KMO prescrive il blocco sincrono all'interno del turno, mentre OW incoraggia a lasciare il turno non bloccato.
2. **Cadenza dell'health check in Fase 1:**
   - OW (righe 54-56): *"Confirm the Executor's engine ... once per session or after a dispatch failure (do not re-run health/config checks before every single task)."*
   - KMO (riga 42): *"Use `kilo_list_models` and `kilo_auth_status` to ensure Kilo's engine and models are ready"* (nessuna limitazione di frequenza, causando chiamate ridondanti).

---

## 2. Sovrapposizione dei trigger

### Confronto delle descrizioni
- **OW (riga 3):** `"...Use when coordinating development work delegated to another agent, or when new tasks appear during a working session."`
- **KMO (riga 3):** `"...Use when coordinating development work through the kilo-mcp tools, or when new tasks appear during a working session."`

### Scenari di caricamento
- **L'agente carica solo OW:** Quando coordina subagent/worktree nativi (senza MCP) o delega ad agenti diversi da Kilo (Codex, Claude-in-Claude).
- **L'agente carica solo KMO:** Quando il prompt dell'utente fa riferimento esplicito a Kilo o ai tool `kilo-mcp`.
- **L'agente carica ENTRAMBE (Conflitto):** Ogni volta che l'utente chiede di "delegare questo task", "coordinare i worktree" o "catturare questo nuovo task emergente". Entrambe le skill rivendicano l'identica clausola di attivazione `"or when new tasks appear during a working session"`, portando Claude a caricarle entrambe nel contesto (sprecando circa 12k token in tabelle economiche duplicate) o a scegliere arbitrariamente.

---

## 3. Verdetto

**Incompatibili solo nella formulazione/trigger, pienamente compatibili nella sostanza.**
KMO non è una filosofia di orchestrazione alternativa; è il binding concreto per `kilo-mcp` di OW. Le differenze derivano interamente dai binding ai tool concreti più omissioni accidentali negli override del template in `bindings/orchestration-workflow.json`.

---

## 4. Proposta: regole di precedenza e presa d'atto nel Doctor

### Testo concreto per `orchestration-workflow`
Aggiungere sotto `## Quick Reference` / `## Role discipline`:
```markdown
### Precedence with Bound Skills
If `kilo-mcp-orchestrator` is also loaded and the execution channel is Kilo via `kilo-mcp`, defer tool-level invocation details (e.g. `kilo_implement`, `kilo_task_wait`, `kilo_rag_search`, `kilo_log_issue`) to `kilo-mcp-orchestrator`. All architectural rules—the 6-phase lifecycle, verification modes (`independent-session`, `cross-agent`, etc.), the Post-Verification Decision Table, formal task states (`open` → `delivered` → `verified` → `done`), and economic rules—remain authoritative as defined here.
```

### Testo concreto per `kilo-mcp-orchestrator`
Aggiungere sotto `## Quick Reference` / `## Role discipline`:
```markdown
### Precedence with Generic Skills
This skill provides the concrete `kilo-mcp` tool bindings for orchestrating Kilo. When `orchestration-workflow` is also loaded, this skill specializes the tool calls (`kilo_implement`, `kilo_task_wait`, etc.), while `orchestration-workflow` governs the overarching architecture: task state transitions, verification modes, the Post-Verification Decision Table, and harness safety.
```

### Adeguamento delle descrizioni per eliminare la competizione sui trigger
- **Descrizione OW:**
  `"Orchestrate an Executor agent through the Architect/Executor pattern - discovery-first exploration, isolation before delegating, non-blocking parallel delegation, complexity-scaled monitoring/intervention, real verification, defect telemetry, and capture of emergent tasks. Use for native subagent/worktree orchestration or multi-framework pipelines. When delegating specifically to Kilo via kilo-mcp tools, prefer kilo-mcp-orchestrator."`
- **Descrizione KMO:**
  `"Tool-level binding for orchestrating Kilo via the kilo-mcp server - kilo_rag_search, kilo_implement with worktree isolation, deterministic wait (kilo_task_wait), progress monitoring, and defect telemetry (kilo_log_issue). Use specifically when executing tasks through kilo-mcp tools. For generic multi-agent coordination or native worktrees, use orchestration-workflow."`

### Gestione nell'Environment Doctor
Attualmente il Doctor tratta la coppia generica + associata come un `trigger-conflict` rosso non risolvibile sotto la policy `claude=bound` (T016:26, 126-134). Il Doctor dovrebbe classificare la coppia come **`acknowledged` (severità info, non un errore)** quando:
1. Entrambe le skill riportano dichiarazioni di precedenza reciproca (oppure il Doctor verifica che KMO è un binding dichiarato di OW tramite `bindings/orchestration-workflow.json`).
2. L'utente ha preso atto della coesistenza in `~/.config/ai-orchestration/doctor-ack.json`.
Non si deve mai consigliare di disabilitare `architect-side@ai-orchestration`, poiché ciò rimuove 5 skill essenziali non in conflitto (`task-pipeline`, `task-spec-authoring`, `task-worktree-ops`, `conflict-resolver`, `orchestration-metrics`).

---

## 5. Correzioni testuali obbligatorie (indipendenti dalla precedenza)

1. **Ripristinare l'architettura di base in `kilo-mcp/bindings/orchestration-workflow.json`:**
   Rifattorizzare `SKILL.template.md` in modo che gli override di `phase5_body` non cancellino le modalità di verifica (OW:153-170) e la tabella decisionale post-verifica (OW:172-182), e gli override di `closing` non cancellino la tabella a 10 stati (OW:383-407) e i controlli sullo scaffolding dell'harness (OW:367-381).
2. **Allineare la frequenza dell'health-check:**
   Aggiungere `"once per session or after a dispatch failure"` alla Fase 1 di KMO (KMO:42) per allinearsi a OW:54-56 ed evitare polling inutili su modelli e autenticazione.
3. **Ripristinare l'annotazione di consegna sul branch:**
   Includere nella Fase 4 di KMO la regola che richiede `- state: delivered` con `verification pending:` sul branch del worktree (OW:134-138).
4. **Armonizzare polling di completamento e attesa bloccante:**
   Chiarire in KMO:65,69 che `kilo_task_wait` è raccomandato quando si opera in un host interattivo che supporta chiamate MCP bloccanti, mentre la delega non bloccante con monitoraggio scollegato si applica ai flussi di lavoro CLI/headless.
