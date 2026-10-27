# Q002 Le skill a livello di progetto in ai-orchestration (.claude, .codex, .kilo) sono state installate intenzionalmente e devono rimanere

- id: Q002
- question: Le skill a livello di progetto in ai-orchestration (.claude, .codex, .kilo) sono state installate intenzionalmente e devono rimanere?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A
- applied: yes
- short: Copie skill di progetto

## Context

Oggi alle 13:13 sono apparse copie di skill e una configurazione MCP di progetto non tracciate in ai-orchestration/: .claude/skills (5), .codex/skills (12), .kilo/skills, .kilo/agents, .kilo/kilo.json. Nessun log dei task di Kilo contiene un comando di installazione; la UI sulla porta 8780 serve questo workspace, quindi l'origine probabile è un'installazione a livello di progetto dalla scheda Installer. Le copie di progetto duplicano le copie globali e dei plugin e aggiungono segnalazioni nel Doctor. Fonte: tasks/env-doctor/notes/T016-report.md (studio sul Doctor, 2026-10-17).

## Options

- **A** — Rimuoverle: eliminare le copie non tracciate (sono riproducibili dal repository sorgente)
- **B** — Mantenerle e ignorarle: mantenerle e aggiungere le cartelle a .gitignore
- **C** — Mantenerle e committarle: versionarle come skill di progetto proprie del repository

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17
