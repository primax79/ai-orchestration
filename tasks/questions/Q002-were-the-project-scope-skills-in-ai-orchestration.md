# Q002 Were the project-scope skills in ai-orchestration (.claude, .codex, .kilo) installed on purpose, and should they stay

- id: Q002
- question: Were the project-scope skills in ai-orchestration (.claude, .codex, .kilo) installed on purpose, and should they stay?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A

## Context

At 13:13 today skill copies and a project MCP config appeared, untracked, in ai-orchestration/: .claude/skills (5), .codex/skills (12), .kilo/skills, .kilo/agents, .kilo/kilo.json. No Kilo task log contains an install command; the UI on port 8780 serves this workspace, so a project-scope install from the Installer tab is the likely origin. Project copies duplicate the global and plugin copies and add Doctor findings. Source: tasks/env-doctor/notes/T016-report.md (Doctor study, 2026-10-17).

## Options

- **A** — Remove them: delete the untracked copies (they are reproducible from the source repo)
- **B** — Keep and ignore: keep them and add the folders to .gitignore
- **C** — Keep and commit: version them as the repo's own project skills

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17
