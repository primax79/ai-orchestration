# T075 Pulsante Valida e chiudi sulla colonna Delivered e sul singolo task

- id: T075
- title: Pulsante Valida e chiudi sulla colonna Delivered e sul singolo task
- category: ui
- priority: P2
- priority-reason: Richiesta del proprietario 2026-10-27: chiudere da UI i task consegnati che ha validato usandoli
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: owner 2026-10-27: 'mi metti in done il pulsante per richiedere la validazione? sia globale sulla colonna, sia su singolo task'
- paths: ai-orchestration-ui/backend/server.py, ai-orchestration-ui/frontend/src/components/BacklogManager.tsx, ai-orchestration-ui/frontend/src/components/TaskDetailModal.tsx, vscode-ai-orchestration/src/views/dashboard-panel.ts
- handoff: Read tasks/ui/T075-pulsante-richiedi-validazione-sulla-colonna-done-e.md, do the open steps, run the Verification, update the task and the registry.
- short: Valida e chiudi da UI

## Goal

Richiesta del proprietario (2026-10-27), chiarita: "intendevo il contrario, volevo il pulsante per validare e chiudere".
Nella vista Kanban, colonna Delivered (e Verified): un pulsante "Validate & close" sull'intestazione, che agisce sui
task visibili della colonna, e uno su ogni scheda e nel dettaglio del task. Apre una conferma con l'elenco dei task e
una nota facoltativa (esito della validazione); conferma -> per ognuno `ai-orch tasks transition <id> done --verifier
owner` (il percorso delivered -> verified -> done in un comando, T035), con anteprima e hash dove il motore li prevede.
Il proprietario è il verificatore indipendente: la UI lo registra come `owner`. Stessa funzione nell'estensione VS Code.

## Steps

- [ ] Backend: endpoint singolo e bulk 'validate-close' (anteprima dell'insieme, poi apply) che chiama transition <id> done --verifier owner con nota
- [ ] Frontend: pulsanti su colonna Delivered/Verified, scheda e dettaglio; conferma con elenco e nota; refresh via websocket
- [ ] Estensione: handler del bridge per la stessa azione; sync del webview; rilascio

## Verification

- Test del backend (singolo e bulk, anteprima senza scritture); prova su un registro di copia: 2 task delivered -> done con verifier owner e riga di Log; il proprietario valida usandola
