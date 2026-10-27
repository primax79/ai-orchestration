# N075 questions ask sovrascrive waiting-on invece di accumulare

- id: N075
- title: questions ask sovrascrive waiting-on invece di accumulare
- kind: bug
- status: ready
- created: 2026-10-27T23:13:43.288438+00:00
- author: ai-coding-tools-87
- about: T073
- produced: -
- processed-by: -
- short: waiting-on sovrascritto

Registrando 7 domande con --blocks T073 (Q025-Q031), il campo decider di T073 le elenca tutte, ma waiting-on contiene solo question:Q031. Atteso: waiting-on elenca tutte le domande aperte che bloccano il task (o un riferimento equivalente), e risolvere una domanda toglie solo quella. Altrimenti, risposta Q031 prima delle altre sblocca il task mentre Q025-Q030 sono ancora aperte.
