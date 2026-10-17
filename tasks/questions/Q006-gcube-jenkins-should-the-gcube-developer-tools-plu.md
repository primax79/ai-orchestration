# Q006 gcube-jenkins: should the gcube-developer-tools plugin become the canonical copy, with the env examples ported into it

- id: Q006
- question: gcube-jenkins: should the gcube-developer-tools plugin become the canonical copy, with the env examples ported into it?
- status: open
- blocks: T019 (in progress)
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-18
- origin-run: -
- open-answer: yes
- recommended: A

## Context

Two copies exist. The standalone ~/.kilo/skills/gcube-jenkins has references/env/{java17,java8}.env.example, used by gcube_credentials_check.sh; the plugin copy (gcube-developer-tools@gcube-ai-toolkit 0.2.1) lacks them because gcube-ai-toolkit/.gitignore line 254 'ENV/' also ignores references/env on macOS. SKILL.md and scripts are otherwise identical. Details: tasks/env-doctor/notes/T019-skill-diffs.md section 1.

## Options

- **A** — Plugin canonical, port the env examples: whitelist references/env in gcube-ai-toolkit/.gitignore, commit, bump and update the plugin, retire the standalone copy
- **B** — Standalone canonical: keep ~/.kilo/skills/gcube-jenkins and mark the duplicate as acknowledged in the Doctor
- **C** — Plugin canonical as it is: drop the env examples and remove the standalone copy

## Answer

- choice: -
- answered-by: -
- answered: -
