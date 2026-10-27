# Q005 Per gcube-jenkins, gcube-security-audit e frontend-design, quale copia è canonica: quella standalone o quella del plugin

- id: Q005
- question: Per gcube-jenkins, gcube-security-audit e frontend-design, quale copia è canonica: quella standalone o quella del plugin?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: C
- applied: yes
- short: Copie skill canoniche

## Context

Le copie standalone in ~/.claude/skills contengono file aggiuntivi rispetto alle copie dei plugin (plugin gcube-ai-toolkit e agentic-coding-kit). Claude le carica entrambe. Mantenere la copia del plugin fa perdere i contenuti extra a meno che non vengano portati nei repository sorgente. Fonte: tasks/env-doctor/notes/T016-report.md (studio sul Doctor, 2026-10-17).

## Options

- **A** — Il plugin è canonico, portare i contenuti extra: portare i contenuti aggiuntivi in gcube-ai-toolkit / agentic-coding-kit, poi rimuovere le copie standalone
- **B** — La copia standalone è canonica: mantenere le copie standalone e riconoscere i duplicati
- **C** — Decidere per singola skill: elencare le differenze per ogni skill e decidere una per una

## Answer

- choice: C
- answered-by: owner
- answered: 2026-10-17
