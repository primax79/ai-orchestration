# Q004 Should we bump the plugin versions and update the Claude plugins now

- id: Q004
- question: Should we bump the plugin versions and update the Claude plugins now?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A

## Context

Claude runs architect-side@ai-orchestration 0.3.0 and architect-side@kilo-mcp 0.2.2 from its plugin cache; the sources are 69 and 7 commits ahead with unchanged version strings, so Claude will not update them. Updating requires bumping versions, pushing, and updating the plugins in Claude. The push is outward-facing and waits for your approval anyway. Source: tasks/env-doctor/notes/T016-report.md (Doctor study, 2026-10-17).

## Options

- **A** — Yes, at the end of initiative 06: bump, push, update plugins once the safety work is complete
- **B** — Yes, now: bump and push now, accepting partial features
- **C** — No: keep the cached versions until further notice

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17
