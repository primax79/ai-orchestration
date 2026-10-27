# Q027 Lo strumento può leggere gli archivi locali dei provider (~/.claude/projects, Kilo, Codex) e i processi per trovare sessioni non registrate

- id: Q027
- question: Lo strumento può leggere gli archivi locali dei provider (~/.claude/projects, Kilo, Codex) e i processi per trovare sessioni non registrate?
- status: answered
- blocks: T073 (waiting)
- decider: owner
- asked-by: ai-coding-tools-87
- asked: 2026-10-28
- origin-run: -
- open-answer: yes
- recommended: A
- applied: no
- short: Lettura archivi dei provider

## Context

Studio tasks/specs/orchestrator-control-plane-study.md (T073), rivisto da Codex; vale per ogni chiave di ruolo (progetto o _workspace, spec orchestrator-role-per-project). §6 Q-C.

## Options

- **A** — Sì, su richiesta, solo in lettura e solo per i workspace noti, per mostrare suggerimenti nella UI
- **B** — No, solo sessioni registrate esplicitamente

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-28
