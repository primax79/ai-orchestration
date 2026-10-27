# 08 - Domande bloccanti (formato, motore, UI delle risposte in sospeso)

- **Short:** Domande bloccanti

> **Derived from:** [`../specs/blocking-questions.md`](../../specs/blocking-questions.md). Leggere prima la specifica; questo piano non la ripete.

## Ondate

| Ondata | Task |
| --- | --- |
| 1 (dopo 06.1, stesso file) | 08.1 |
| 2 | 08.2 (skill), 08.3 (backend UI, dopo 06.7) in parallelo |
| 3 | 08.4 (frontend, dopo 06.8) |
| 4 | 08.5 (VS Code, dopo 06.9); 08.6 (risposta e ripresa, dopo 07.6/07.7) |

## Tasks (One Task = One Commit)

## Modifiche dopo la revisione 2 (2026-10-16)

La specifica ora si apre con il §0 "Amendments after review 2" (Q1–Q10). Da esso discendono queste modifiche ai task, e l'ordine delle corsie si trova in `../06-control-plane-safety/plan.md`:

- **08.1** ora dipende da **06.10** (lock di scrittura sui task), non solo da 06.1. Copre anche Q1–Q7 e Q9. La sua verifica dal vivo usa una **fixture usa e getta** con task legacy `decider: owner: <text>`: T007, T009 e T010 portano `decider: -`, quindi il testo precedente del piano non era corretto.
- **08.2** documenta Q8 per le skill: gli agenti nelle esecuzioni emettono il blocco, le sessioni interattive invocano `questions ask`.
- **08.4** aggiunge Q10 e specifica 06 A12 (fixture XSS: un payload `<script>` / `<img onerror>` nel contesto di una domanda viene renderizzato inerte).
- **08.6** non gestisce più la registrazione da parte del supervisore; quella è passata a **07.10**. 08.6 riguarda solo la UI: "Answer and resume run", dopo 07.7, 07.10 e 08.4.

> **2026-10-17:** 08.6 "Answer and resume run" è superato dall'iniziativa 12 (regola di trigger `resume-origin` su `question.answered`, task 12.4). Non viene più sviluppato qui.

## Closed

### 08.1 - Motore: file delle domande, validatore, `ai-orch questions list|show|ask|answer|withdraw`, regione Decisions dalle domande aperte

- **Status:** `done` (2026-10-17) · **Short:** Motore delle domande · **Profile:** `deep-reasoning` · **Depends on:** 06.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`, `.../scripts/test_tasks_engine.py`, `bin/ai-orch`, `tasks/specs/task-and-state-model.md` (aggiunta della sezione sul modello delle domande)
- **Goal:** Specifica §2 e §3 integralmente:
  - il formato e il validatore;
  - allocazione degli id sotto lock;
  - il collegamento `waiting` del task e il suo ripristino;
  - conversione `--from-task`;
  - la regione Decisions generata.
- **Verification:** Test:
  - ogni regola del validatore (ordine delle intestazioni, una domanda senza `?` o oltre 160 caratteri, un `recommended` sconosciuto, `choice: open` senza testo o con `open-answer: no`, un id `blocks` inesistente);
  - `ask` blocca un task `in progress` e `answer` lo ripristina;
  - due chiamate `ask` concorrenti ottengono id distinti;
  - la regione Decisions genera una riga per ogni domanda aperta;
  - un `decider: owner: ...` legacy passa ancora la validazione con un avviso.

  Dal vivo: eseguire `questions ask --from-task` su una copia di `tasks/` del workspace per T007, T009 e T010 (che portano testi decider legacy) ed esaminare il risultato.

### 08.2 - Skill: gli agenti registrano le domande bloccanti nel formato previsto

- **Status:** `done` (2026-10-17) · **Short:** Domande dagli agenti · **Profile:** `bulk-execution` · **Depends on:** 08.1 · **Repo:** `ai-orchestration/`
- **Focus files:** `plugins/architect-side/skills/task-pipeline/SKILL.md`, `.../task-pipeline/references/template.md`, `plugins/architect-side/skills/orchestration-workflow/SKILL.template.md`, `plugins/executor-side/skills/executor-contract/SKILL.template.md`, i file `SKILL.md` generati (rigenerare, mai modificare a mano), i file `index.json`
- **Goal:** Specifica §4. Mantenere le skill indipendenti dal protocollo: nominare `ai-orch questions ask` come CLI di questo kit (consentito), mai un tool MCP concreto. Rigenerare le skill generiche.
- **Verification:**
  - `python3 ./scripts/regenerate_generic_skills.py && python3 ./scripts/generate_skill_indices.py` termina senza errori.
  - Il Final Report segnala che le copie vincolate di `kilo-mcp` richiedono `regenerate_bound_skills.py` (follow-up dell'orchestratore in `../kilo-mcp`).

### 08.3 - Backend UI: endpoint delle domande

- **Status:** `done` (2026-10-17) · **Short:** Endpoint delle domande · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 08.1, 06.7 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `backend/server.py`, `backend/test_server.py`
- **Goal:** Aggiungere questi endpoint come sottili wrapper asincroni:
  - `GET /api/questions?status&blocks`
  - `GET /api/questions/{id}`
  - `POST /api/questions` (ask)
  - `POST /api/questions/{id}/answer`
  - `POST /api/questions/{id}/withdraw`

  Il watcher segnala le modifiche alle domande come `areas:["questions"]`.
- **Verification:** Test HTTP per ask → list → answer → stato del task ripristinato; una risposta non valida → 400 con il messaggio del validatore.

### 08.4 - Frontend: scheda Decisions, badge nella navbar, sezione Questions nella modale del task, modulo di invio domanda

- **Status:** `done` (2026-10-17) · **Short:** Scheda Decisions · **Size:** M · **Profile:** `bulk-execution` · **Depends on:** 08.3, 06.8 · **Repo:** `ai-orchestration-ui/`
- **Focus files:** `frontend/src/**`, `frontend/dist/**`
- **Goal:** Specifica §5, ad eccezione di "Answer and resume run".
- **Verification:**
  - `npm run build` termina senza errori.
  - Dal vivo con il server MCP Playwright su un workspace temporaneo: porre una domanda dalla modale del task → conteggio badge 1 → rispondere con un'opzione → il task torna al suo stato precedente; una risposta aperta richiede del testo; Withdraw richiede una motivazione.

### 08.5 - VS Code: albero "Decisions Waiting" dai file delle domande

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Albero Decisions VS Code · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 08.4, 06.9 · **Repo:** `vscode-ai-orchestration/`
- **Focus files:** `src/views/*decision*`, `src/views/dashboard-panel.ts`, `dist-webview/**`
- **Goal:** Specifica §5 "VS Code".
- **Verification:**
  - `npm run compile` termina senza errori.
  - Dal vivo: l'albero elenca le domande aperte e un clic apre la scheda corrispondente.

### 08.6 - "Rispondi e riprendi l'esecuzione"

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Rispondi e riprendi · **Size:** S · **Profile:** `bulk-execution` · **Depends on:** 08.4, 07.7 · **Repo:** `ai-orchestration-ui/` (+ `ai-orchestration/` se la registrazione dei blocchi domanda da parte del supervisore in 07.3 richiede un follow-up)
- **Focus files:** `frontend/src/**`, `backend/server.py`
- **Goal:**
  - specifica §5 "Answer and resume run";
  - specifica §4 registrazione del blocco di fallback da parte del supervisore delle esecuzioni, se 07.3 non l'ha già fatto.
- **Verification:** Dal vivo con un'esecuzione reale (basta un solo tool) istruita a porre una domanda: la domanda compare; "Answer and resume" continua la medesima sessione e l'agente recepisce la risposta.

### 08.7 - VS Code: notifica toast per le nuove domande e badge nella barra di stato

- **Status:** `done` (2026-10-23; owner; Validato dalle suite di test automatici e approvato dall'owner per la pulizia) · **Short:** Toast per le domande · **Size:** S · **Depends on:** 08.5 (corsia VS Code) · **Repo:** `vscode-ai-orchestration/`
- **Origin:** richiesta dell'owner (2026-10-17).
- **Goal:**
  - Una nuova domanda aperta (un id mai visto prima) mostra una notifica VS Code (`showInformationMessage`) con il testo breve e le azioni "Open" (mostra la dashboard sulla scheda Decisions e su quella domanda, o almeno sulla scheda) e "Later".
  - Un elemento nella barra di stato mostra il conteggio delle domande aperte (`$(question) N`), con sfondo di avviso quando N > 0 e nascosto o neutro quando N = 0. Un clic su di esso apre Decisions.
  - Nessun toast all'avvio per le domande già esistenti; solo il badge.
  - Gli id notificati vengono memorizzati in `workspaceState`, così un ricaricamento non invia nuove notifiche.
  - Le domande a cui è stata data risposta o ritirate aggiornano immediatamente il badge.
  - Un'impostazione `aiOrchestration.notifyNewQuestions` (predefinita a true).
- **Verification:**
  - `npm run compile` termina senza errori.
  - Un test guida la logica di calcolo delle differenze (insieme aperto prima e dopo, archivio degli id notificati): un nuovo id → una notifica; avvio con id esistenti → nessuna; una domanda con risposta → il conteggio diminuisce.
  - Dal vivo in un Extension Development Host con l'owner.
