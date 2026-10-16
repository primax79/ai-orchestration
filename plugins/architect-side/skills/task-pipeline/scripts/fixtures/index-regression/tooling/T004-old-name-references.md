# T004 Old skill name references

- id: T004
- title: Old skill name references
- category: tooling
- priority: P2
- priority-reason: A stale name silently breaks agent configs after the rename
- next-up: yes
- state: open
- executor: self
- depends-on: -
- decider: -
- sources: status/handoff-2026-10-08-emergent-tasks-convention.md (Open 4)
- paths: ~/.kilo, ~/.config/kilo, kilo-mcp/agents*
- handoff: Read tasks/tooling/T004-old-name-references.md, do the open steps, update the task and this index.

## Goal

Remove remaining references to the old skill name mcp-orchestrator.

## Steps

1. Fix each hit across the configs.

## Verification

- Grep shows zero hits.
