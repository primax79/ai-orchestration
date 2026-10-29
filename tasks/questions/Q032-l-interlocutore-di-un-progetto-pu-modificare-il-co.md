# Q032 L'interlocutore di un progetto può modificare il codice di prodotto, o solo conversare e smistare il lavoro

- id: Q032
- question: L'interlocutore di un progetto può modificare il codice di prodotto, o solo conversare e smistare il lavoro?
- status: open
- blocks: -
- decider: owner
- asked-by: owner
- asked: 2026-10-29
- origin-run: -
- open-answer: no
- recommended: B
- short: Interlocutore e codice

## Context

Spec multi-macchina §7: l'interlocutore è la sessione con cui l'owner parla per un progetto (dalla console o in terminale): risponde su stato e decisioni, trasforma le richieste in note, task e risposte, passa il lavoro all'orchestratore, e 'non scrive mai codice di prodotto'. Per la chat contestuale (T074) l'owner aveva risposto Q013=A: quella sessione può modificare il codice. Serve una regola per l'interlocutore prima del task 19.14 (Ruoli e handoff).

## Options

- **A** — Solo conversazione e smistamento: ogni modifica al codice diventa un task per un executor (tracciata, verificata, ma più lenta per le piccole cose)
- **B** — Piccole modifiche su richiesta esplicita dell'owner, in un worktree e con un task micro registrato; il resto va agli executor
- **C** — Come la chat contestuale (Q013=A): può modificare il codice liberamente

## Answer

- choice: -
- answered-by: -
- answered: -
