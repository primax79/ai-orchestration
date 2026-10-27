# Q011 Separiamo l'approvazione di uno use case dal suo stadio derivato dai task

- id: Q011
- question: Separiamo l'approvazione di uno use case dal suo stadio derivato dai task?
- status: answered
- blocks: 17.5 (open)
- decider: owner
- asked-by: ai-coding-tools-d8
- asked: 2026-10-27
- origin-run: -
- open-answer: yes
- recommended: A
- applied: yes
- short: Approvazione e stadio use case

## Context

Nella nota N072 'draft' indica sia 'nessun task' sia 'non ancora approvato da te'. Il flusso use-case-first chiede che tu approvi gli use case PRIMA di creare i task; lo stadio invece si ricava dai task (draft, planned, in development, ready, verified/failing). Spec: tasks/specs/use-cases-drive-tasks.md §3. Codex ha segnalato che non è una scelta che posso prendere io.

## Options

- **A** — Due campi: approval (proposed/approved/deprecated) scritto da te, stage calcolato dai task; si può approvare uno use case prima che esistano i task
- **B** — Un solo campo stage: 'draft' vale sia 'senza task' sia 'non approvato'; l'approvazione è implicita quando si creano i task
- **C** — Un solo campo stage con uno stadio in più 'approved' tra draft e planned

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-27
