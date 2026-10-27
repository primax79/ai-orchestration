# Q008 frontend-design: third-party-skills@agentic-coding-kit deve restare la copia canonica, mantenendo sincronizzata la copia di Kilo

- id: Q008
- question: frontend-design: third-party-skills@agentic-coding-kit deve restare la copia canonica, mantenendo sincronizzata la copia di Kilo?
- status: answered
- blocks: T019 (waiting)
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-18
- origin-run: -
- open-answer: yes
- recommended: A
- short: Canonico frontend-design

## Context

La copia standalone ~/.kilo/skills/frontend-design è identica byte per byte alla copia in third-party-skills di agentic-coding-kit (85 righe); la cache del plugin di Claude 0.1.0 differisce solo nella formattazione YAML della descrizione. Il repository claude-plugins-official di Anthropic distribuisce un prompt per frontend-design diverso e più lungo (180 righe). Dettagli: T019-skill-diffs.md sezione 3.

## Options

- **A** — agentic-coding-kit canonica: mantenerla come sorgente, tenere sincronizzata la copia di Kilo, il Doctor le tratta come identiche
- **B** — Adottare la versione di Anthropic: portare il prompt ufficiale di 180 righe in agentic-coding-kit e aggiornare entrambe le copie
- **C** — Ritirare la copia di Kilo: affidarsi esclusivamente al plugin di Claude (Kilo non disporrebbe più della skill)

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-18

```text
Owner 2026-10-18: recommended option A for all three (Q006-Q008).
```
