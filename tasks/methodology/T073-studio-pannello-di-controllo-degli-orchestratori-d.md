# T073 Studio: pannello di controllo degli orchestratori di tutti i workspace, handoff e coerenza dei registri

- id: T073
- title: Studio: pannello di controllo degli orchestratori di tutti i workspace, handoff e coerenza dei registri
- category: methodology
- priority: P1
- priority-reason: Richiesta del proprietario 2026-10-27: oggi i registri non concordano e il ruolo di orchestratore non è visibile né gestibile
- next-up: no
- state: in progress
- executor: kilo
- depends-on: -
- decider: owner
- sources: _inbox/analyzed/20261027-144545-in-depth-study-orchestrator-feedback-han/note.md
- paths: N068; N069; specs ui-multi-project.md, orchestration-broker-mcp.md, orchestration-extension-spec.md, events-and-triggers.md; UC028, UC030, UC033, UC037
- handoff: Read tasks/methodology/T073-studio-pannello-di-controllo-degli-orchestratori-d.md, do the open steps, run the Verification, update the task and the registry.
- short: Studio pannello orchestratori

## Goal

Owner request (2026-10-27, verbatim intent): we need a mechanism that gives feedback on the orchestrator, allows handoff and reassignment, etc.; ask for an in-depth study. Owner idea: an additional panel in ai-orchestration listing all existing workspaces, from which you can communicate with them and see their state.

## Steps

- [x] Bozza dello studio (Kilo, sola lettura sullo stato reale): problema, pezzi esistenti e lacune, opzioni con pro e contro, raccomandazione, use case da aggiungere o cambiare, piano in iniziative — scritto in `tasks/specs/orchestrator-control-plane-study.md`
- [ ] Revisione indipendente di Codex e dell'architetto, convergenza sulle divergenze
- [ ] Revisione del proprietario prima di qualsiasi implementazione

## Verification

- Studio in tasks/specs/ che copre i 5 temi della nota N071 con evidenze dello stato del 2026-10-27; revisione del proprietario registrata nel task

## Log

- 2026-10-27, kilo: bozza dello studio scritta
- 2026-10-27, kilo: studio rivisto dopo la revisione di Codex
