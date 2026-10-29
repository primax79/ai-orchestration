# UC038 - Owner detects and upgrades a project that drifted from the current ai-orchestration conventions

- id: UC038
- title: Owner detects and upgrades a project that drifted from the current ai-orchestration conventions
- actor: Owner
- approval: proposed
- priority: P1
- linked-tasks: 19.1, 19.2, 19.3
- verification-type: e2e
- last-tested: -
- last-verdict: -
- short: Project drift upgrade

## Description & Business Value
Projects adopted ai-orchestration at different times; nothing told ricerca_auto it was 2 weeks behind (no config, unregistered, index without markers, duplicated AGENTS.md). The owner needs one command that reports drift and one that fixes it safely. Source: tasks/specs/multi-machine-development-architecture.md

## Preconditions
A project with a tasks/ tree created by an older ai-orchestration version

## Scenario / Interaction Steps
1. Owner runs ai-orch doctor in the project. 2. It lists each drift item with severity and the convention version the project is on. 3. Owner runs ai-orch upgrade (preview with plan hash). 4. Owner applies with --apply --expect-hash. 5. doctor reports no drift and tasks validate is clean.

## Automated Verification Command
```bash
echo 'No verification command specified'
```

## Acceptance Criteria
- [ ] doctor reports missing config, unregistered workspace, index without markers, stale or duplicated rendered AGENTS.md, old header fields
- [ ] upgrade fixes them without touching active executor worktrees
- [ ] the convention version is recorded per project

## AI Validation Log

