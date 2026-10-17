# Q008 frontend-design: should third-party-skills@agentic-coding-kit stay the canonical copy, with Kilo's copy kept in sync

- id: Q008
- question: frontend-design: should third-party-skills@agentic-coding-kit stay the canonical copy, with Kilo's copy kept in sync?
- status: open
- blocks: T019 (waiting)
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-18
- origin-run: -
- open-answer: yes
- recommended: A

## Context

The standalone ~/.kilo/skills/frontend-design is byte-identical to agentic-coding-kit's third-party-skills copy (85 lines); the Claude plugin cache 0.1.0 differs only in YAML formatting of the description. Anthropic's claude-plugins-official ships a different, longer (180-line) frontend-design prompt. Details: T019-skill-diffs.md section 3.

## Options

- **A** — agentic-coding-kit canonical: keep it as the source, keep Kilo's copy in sync, the Doctor treats them as identical
- **B** — Adopt Anthropic's version: port the official 180-line prompt into agentic-coding-kit and update both copies
- **C** — Retire Kilo's copy: rely on the Claude plugin only (Kilo would no longer have the skill)

## Answer

- choice: -
- answered-by: -
- answered: -
