# T031 Completamento condizionato: età della domanda nell'indice; posizione dell'header conditions:

- id: T031
- title: Completamento condizionato: età della domanda nell'indice; posizione dell'header conditions:
- category: server-and-bindings
- priority: P3
- priority-reason: Follow-up di T030 segnalato dalla sessione centrale di Evolution Assurance (docs/08 §7.15)
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Leggere tasks/server-and-bindings/T031-conditional-done-question-age-in-the-index-conditi.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: d4science-evolution-assurance-37
- short: Follow-up done condizionato

## Goal

(1) La sezione Conditional di 00-INDEX.md mostra, per ciascun task, ogni domanda condizione con la sua età in giorni e il relativo decisore (ad es. 'Q003 (9 d, owner)'); le condizioni più vecchie di 7 giorni sono elencate in una riga sintetica 'stale conditions' con il rispettivo decisore; gli stessi dati sono presenti nel JSON (conditions: [{id, status, age_days, decider}]). (2) Un header con conditions: in una posizione non canonica viene rifiutato senza spiegarne il motivo: accettare i campi opzionali in qualsiasi posizione, oppure fare in modo che l'errore di ordinamento indichi l'ordine atteso (mantenendo la coerenza con il comportamento del motore per gli altri campi opzionali).

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
