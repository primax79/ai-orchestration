# T075 Pulsante Richiedi validazione sulla colonna Done e sul singolo task

- id: T075
- title: Pulsante Richiedi validazione sulla colonna Done e sul singolo task
- category: ui
- priority: P2
- priority-reason: Richiesta del proprietario 2026-10-27: molti task done with a caveat attendono una validazione d'uso
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: owner 2026-10-27: 'mi metti in done il pulsante per richiedere la validazione? sia globale sulla colonna, sia su singolo task'
- paths: ai-orchestration-ui/backend/server.py, ai-orchestration-ui/frontend/src/components/BacklogManager.tsx, ai-orchestration-ui/frontend/src/components/TaskDetailModal.tsx, vscode-ai-orchestration/src/views/dashboard-panel.ts
- handoff: Read tasks/ui/T075-pulsante-richiedi-validazione-sulla-colonna-done-e.md, do the open steps, run the Verification, update the task and the registry.
- short: Richiedi validazione da UI

## Goal

Nella vista Kanban, colonna Done: un pulsante 'Request validation' sull'intestazione (agisce sui task visibili della colonna, per default solo quelli 'done with a caveat') e uno su ogni scheda e nel dettaglio del task. Apre una finestra: destinatario (owner per default, oppure un workspace registrato o una sessione), cosa verificare (precompilato dalla Verification del task), elenco dei task coinvolti; conferma -> per ognuno 'ai-orch tasks reopen <id> --to delivered --verify-by <dest> --verify-check <testo>' con anteprima e hash. Stessa funzione nell'estensione VS Code.

## Steps

- [ ] Backend: _handle_reopen passa --to, --verify-by, --verify-check; endpoint bulk con anteprima dell'insieme
- [ ] Frontend: pulsanti su colonna, scheda e dettaglio; finestra di richiesta; refresh via websocket
- [ ] Estensione: handler del bridge per la stessa azione; sync del webview; rilascio

## Verification

- Test del backend (singolo e bulk, anteprima senza scritture); prova nel browser su un registro di copia: richiesta su 2 task con riserva -> tornano delivered con verify-by e compaiono in verification-queue; il proprietario valida usandola
