# T074 Chat contestuale con l'IA su un singolo use case, task o domanda

- id: T074
- title: Chat contestuale con l'IA su un singolo use case, task o domanda
- category: methodology
- priority: P1
- priority-reason: Richiesta del proprietario 2026-10-27: interagire con l'IA a partire dalla vista di un elemento
- next-up: no
- state: open
- executor: kilo
- depends-on: T073
- decider: -
- sources: owner 2026-10-27: 'mi servirebbe poter interagire con ia relativamente a una specifica use-case, task, o questione; nella vista elemento un box in cui mando un messaggio, o apro un pannello contestuale per chat'
- paths: tasks/specs/contextual-element-chat.md, ai-orchestration-ui, vscode-ai-orchestration
- handoff: Read tasks/methodology/T074-chat-contestuale-con-l-ia-su-un-singolo-use-case-t.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: owner
- short: Chat contestuale per elemento

## Goal

Dalla vista di un elemento (use case, task, domanda) il proprietario scrive un messaggio in un box o apre un pannello di chat contestuale; l'IA risponde avendo come contesto quell'elemento e i suoi collegamenti (spec, task, use case, log), e può proporre modifiche all'elemento come azioni proposte da confermare (mai scritture dirette). Ogni elemento ha il suo filo di conversazione persistente, visibile anche nella chat generale. Si parte dalla chat attuale (turni owner_chat in coda all'orchestratore, azioni proposte). Va deciso chi risponde: orchestratore headless, sessione interattiva che orchestra (via broker, vedi T073) o un agente dedicato avviato per l'elemento.

## Usi previsti (proprietario, 2026-10-27)

"così gli dico ad es. una modifica al volo, o ci ragiono sopra"; "ovviamente può generare modifiche"; "semplicemente
l'IA ha tutti i tool a disposizione per interagire con gli elementi, cambia solo il contesto della conversazione".

- L'IA della chat contestuale è un'IA con tutti i tool (gli stessi `ai-orch` e di file che usa una sessione di
  orchestrazione): legge, modifica, crea task, use case, domande, transizioni. Non c'è un meccanismo speciale di
  "modifiche proposte": vale il modo di permesso della sessione che risponde, come in qualsiasi sessione.
- Cambia solo il contesto: la conversazione parte dall'elemento (e dai suoi collegamenti) e resta legata a lui.
- Elementi: use case, task (anche di iniziativa), domande e note dell'inbox (proprietario: "ovviamente anche sulle note
  potrebbe servire una chat"; per una nota: chiarirla, smistarla, trasformarla in task o use case).
- Usi tipici: modifica al volo (rapida, pochi secondi) e ragionamento, che può portare a modifiche in qualsiasi momento.

## Steps

- [x] Spec (Kilo, sola lettura sul codice: OrchestratorChatPanel, api_post_orchestrator_chat, turni e azioni proposte, vista dettaglio di task/use case/domanda): modello dei fili per elemento, contesto inviato, chi risponde (opzioni e raccomandazione), azioni proposte, permessi, UI web ed estensione — `tasks/specs/contextual-element-chat.md` (sessione dedicata per elemento con `--resume`, store unificato `orchestrator/turns/` + `threads/`, mockup ASCII)
- [ ] Revisione Codex e dell'architetto; domanda al proprietario su chi risponde
- [ ] Piano in iniziativa dopo l'approvazione

## Verification

- Spec in tasks/specs/contextual-element-chat.md con opzioni, raccomandazione e mockup ASCII della vista elemento; approvata dal proprietario

## Log

- 2026-10-28, owner: state `waiting` -> `open` — Unblocked: question Q017 answered
- 2026-10-27, ai-coding-tools-d8: state `waiting` -> `waiting` — Blocked by question Q017
- 2026-10-27, ai-coding-tools-d8: state `waiting` -> `waiting` — Blocked by question Q016
- 2026-10-27, ai-coding-tools-d8: state `waiting` -> `waiting` — Blocked by question Q015
- 2026-10-27, ai-coding-tools-d8: state `waiting` -> `waiting` — Blocked by question Q014
- 2026-10-27, ai-coding-tools-d8: state `waiting` -> `waiting` — Blocked by question Q013
- 2026-10-27, ai-coding-tools-d8: state `open` -> `waiting` — Blocked by question Q012
- 2026-10-27, kilo: bozza della spec scritta
- 2026-10-27, kilo: spec rivista dopo la revisione di Codex
