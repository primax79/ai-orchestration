# Q004 Dobbiamo incrementare le versioni dei plugin e aggiornare i plugin di Claude ora

- id: Q004
- question: Dobbiamo incrementare le versioni dei plugin e aggiornare i plugin di Claude ora?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A
- applied: yes
- short: Bump versione plugin

## Context

Claude esegue architect-side@ai-orchestration 0.3.0 e architect-side@kilo-mcp 0.2.2 dalla propria cache dei plugin; i sorgenti sono avanti di 69 e 7 commit con stringhe di versione invariate, quindi Claude non li aggiornerà. L'aggiornamento richiede di incrementare le versioni, fare push e aggiornare i plugin in Claude. Il push è visibile esternamente e attende comunque l'approvazione dell'owner. Fonte: tasks/env-doctor/notes/T016-report.md (studio sul Doctor, 2026-10-17).

## Options

- **A** — Sì, alla fine dell'iniziativa 06: incrementare la versione, fare push e aggiornare i plugin una volta completato il lavoro sulla sicurezza
- **B** — Sì, ora: incrementare la versione e fare push subito, accettando funzionalità parziali
- **C** — No: mantenere le versioni in cache fino a nuovo avviso

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17
- text: Applicato il 2026-10-17: iniziativa 06 chiusa (la verifica live 06.9 si appoggia a questa installazione). Rilasciati ai-orchestration architect-side 0.4.0 / shared 0.2.0 / executor-side 0.1.1 e kilo-mcp architect-side 0.2.3 / executor-side 0.1.1; eseguito push; aggiornati i plugin di Claude; reinstallata l'estensione VS Code 0.2.0. D'ora in avanti le funzionalità significative verificate vengono rilasciate senza chiedere (owner, chat 2026-10-17).
