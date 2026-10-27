# T076 Studio delle interazioni del proprietario con task, use case e domande dalla UI

- id: T076
- title: Studio delle interazioni del proprietario con task, use case e domande dalla UI
- category: methodology
- priority: P1
- priority-reason: Richiesta del proprietario 2026-10-27 dopo T074 e T075: le azioni sugli elementi vanno progettate insieme, non una alla volta
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: owner
- sources: owner 2026-10-27: 'mi servirebbe uno studio su questo tipo di interazioni' (dopo la richiesta di Valida e chiudi, T075, e della chat contestuale, T074)
- paths: tasks/specs/owner-interactions-study.md
- handoff: Read tasks/methodology/T076-studio-delle-interazioni-del-proprietario-con-task.md, do the open steps, run the Verification, update the task and the registry.
- short: Studio interazioni UI

## Goal

Uno studio che inventaria e progetta le interazioni del proprietario con gli elementi del registro (task, iniziative, use case, domande, note dell'inbox) dalla UI web e dall'estensione: per ogni stato, quali azioni servono (validare e chiudere, rimandare indietro, chiedere validazione, riaprire, rispondere, approvare uno use case, collegare, cambiare priorità, chattare sull'elemento), dove stanno (colonna, scheda, dettaglio, menu, scorciatoie), singole o di gruppo, quale conferma, quale comando del motore le esegue, cosa c'è già e cosa manca. Include le interazioni con l'IA (T074) e la coerenza tra UI web ed estensione.

## Steps

- [ ] Bozza (Kilo): inventario dei comandi del motore per elemento e stato, copertura attuale della UI e dell'estensione, lacune, matrice azioni x stati x posizione, modelli di conferma, proposta, mockup ASCII, piano
- [ ] Revisione Codex e dell'architetto
- [ ] Revisione del proprietario; poi piano in iniziativa (T075 e T074 vi rientrano)

## Verification

- Studio in tasks/specs/owner-interactions-study.md con la matrice completa e le domande aperte; approvato dal proprietario
