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

## Criterio guida (proprietario, 2026-10-27)

"roba del genere per interagire velocemente": la velocità è il criterio principale. Le azioni frequenti costano un
clic (o un tasto) dal punto in cui si guarda l'elemento: modifica sul posto, menu contestuali, azioni rapide sulla
scheda, scorciatoie da tastiera, nessun cambio di vista. Conferme solo per azioni distruttive o di gruppo; per il resto
applicazione immediata con annullamento rapido. Lo studio misura ogni azione in clic/passi oggi e dopo.

## Esempi del proprietario

- **Modifica sul posto** (2026-10-27): "es. interfaccia per cambiare priorità: click sulla priorità corrente apre un menu
  per cambiarla". Lo stesso modello per gli altri campi brevi (esecutore, stato con le sole transizioni ammesse,
  verify-by, collegamenti agli use case, etichette): il valore è cliccabile ovunque compaia (scheda, riga della coda,
  dettaglio), il menu mostra solo i valori validi, la modifica si applica subito con l'anteprima/hash del motore e un
  annullamento rapido; se il campo richiede una motivazione (priority-reason) il menu la chiede.
- **Valida e chiudi** (T075) e **chat contestuale** (T074).

## Steps

- [ ] Bozza (Kilo): inventario dei comandi del motore per elemento e stato, copertura attuale della UI e dell'estensione, lacune, matrice azioni x stati x posizione, modelli di conferma, proposta, mockup ASCII, piano
- [ ] Revisione Codex e dell'architetto
- [ ] Revisione del proprietario; poi piano in iniziativa (T075 e T074 vi rientrano)

## Verification

- Studio in tasks/specs/owner-interactions-study.md con la matrice completa e le domande aperte; approvato dal proprietario
