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
- decider: owner
- sources: owner 2026-10-27: 'mi servirebbe poter interagire con ia relativamente a una specifica use-case, task, o questione; nella vista elemento un box in cui mando un messaggio, o apro un pannello contestuale per chat'
- paths: tasks/specs/contextual-element-chat.md, ai-orchestration-ui, vscode-ai-orchestration
- handoff: Read tasks/methodology/T074-chat-contestuale-con-l-ia-su-un-singolo-use-case-t.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: owner
- short: Chat contestuale per elemento

## Goal

Dalla vista di un elemento (use case, task, domanda) il proprietario scrive un messaggio in un box o apre un pannello di chat contestuale; l'IA risponde avendo come contesto quell'elemento e i suoi collegamenti (spec, task, use case, log), e può proporre modifiche all'elemento come azioni proposte da confermare (mai scritture dirette). Ogni elemento ha il suo filo di conversazione persistente, visibile anche nella chat generale. Si parte dalla chat attuale (turni owner_chat in coda all'orchestratore, azioni proposte). Va deciso chi risponde: orchestratore headless, sessione interattiva che orchestra (via broker, vedi T073) o un agente dedicato avviato per l'elemento.

## Usi previsti (proprietario, 2026-10-27)

"così gli dico ad es. una modifica al volo, o ci ragiono sopra":

- **Modifica al volo:** chiedo un cambiamento all'elemento (titolo, passi, criteri, priorità, collegamenti); l'IA lo propone come diff dell'elemento e io lo applico con un clic dopo averlo visto (anteprima + hash, come le altre modifiche). Deve essere rapido: pochi secondi, senza aprire altro.
- **Ragionamento:** discuto l'elemento (dubbi, alternative, rischi, impatto su altri task o use case) senza che nulla venga modificato; dal filo posso poi trasformare una conclusione in modifica, in nuovo task o in domanda.

## Steps

- [ ] Spec (Kilo, sola lettura sul codice: OrchestratorChatPanel, api_post_orchestrator_chat, turni e azioni proposte, vista dettaglio di task/use case/domanda): modello dei fili per elemento, contesto inviato, chi risponde (opzioni e raccomandazione), azioni proposte, permessi, UI web ed estensione
- [ ] Revisione Codex e dell'architetto; domanda al proprietario su chi risponde
- [ ] Piano in iniziativa dopo l'approvazione

## Verification

- Spec in tasks/specs/contextual-element-chat.md con opzioni, raccomandazione e mockup ASCII della vista elemento; approvata dal proprietario
