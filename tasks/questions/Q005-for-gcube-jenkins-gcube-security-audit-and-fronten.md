# Q005 For gcube-jenkins, gcube-security-audit and frontend-design, which copy is canonical: the standalone one or the plugin one

- id: Q005
- question: For gcube-jenkins, gcube-security-audit and frontend-design, which copy is canonical: the standalone one or the plugin one?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: C
- applied: yes
- short: Canonical skill copies

## Context

The standalone copies in ~/.claude/skills carry extra content compared with the plugin copies (gcube-ai-toolkit and agentic-coding-kit plugins). Claude loads both. Keeping the plugin copy loses the extras unless they are ported to the source repos. Source: tasks/env-doctor/notes/T016-report.md (Doctor study, 2026-10-17).

## Options

- **A** — Plugin is canonical, port the extras: port the extra content to gcube-ai-toolkit / agentic-coding-kit, then remove the standalone copies
- **B** — Standalone is canonical: keep the standalone copies and acknowledge the duplicates
- **C** — Decide per skill: list the differences per skill and decide one by one

## Answer

- choice: C
- answered-by: owner
- answered: 2026-10-17
