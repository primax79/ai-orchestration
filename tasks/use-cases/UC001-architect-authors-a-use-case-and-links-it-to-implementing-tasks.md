# UC001 - Architect authors a use case and links it to implementing tasks

- id: UC001
- title: Architect authors a use case and links it to implementing tasks
- actor: Architect session
- approval: proposed
- priority: P1
- linked-tasks: 15.1, 15.2, T025
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Author use case

## Description & Business Value
Allows an architect session to define an end-to-end actor scenario with preconditions, steps, verification command, and linked tasks so task Goals and Verification criteria stay anchored to real user value. Source: tasks/specs/use-case-management-and-ai-validation.md §1

## Preconditions
- A project tasks/ directory is initialized.

## Scenario / Interaction Steps
1. The architect runs ai-orch tasks use-cases create with title, short title, actor, priority, linked tasks, and verification command.
2. The engine assigns the next free UC### identifier and writes tasks/use-cases/UC###-<slug>.md.
3. Running ai-orch tasks use-cases show UC### returns the structured header and sections.

## Automated Verification Command
```bash
T=$(mktemp -d) && ./bin/ai-orch tasks use-cases create --tasks-dir "$T/tasks" --title "Sample UC" --short "Sample UC" --actor "Architect session" --status draft --priority P1 --linked-tasks "15.1" && ./bin/ai-orch tasks use-cases show UC001 --tasks-dir "$T/tasks" --json | jq -e ".use_case.id == \"UC001\" and .use_case.short_title == \"Sample UC\"" && rm -rf "$T"
```

## Acceptance Criteria
- [ ] Leaving `--id` empty assigns the next monotonic `UC###` identifier under the write lock.
- [ ] Created file under `tasks/use-cases/UC###-<slug>.md` contains mandatory headers (`id`, `title`, `actor`, `status`, `priority`, `linked-tasks`, `verification-type`, `last-tested`, `last-verdict`, `short`).
- [ ] Bidirectional linkage validates cleanly via `ai-orch tasks validate --tasks-dir tasks` when tasks reference `- use-cases: UC###`.

## AI Validation Log

