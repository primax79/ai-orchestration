# T010 Local skill copies that shadow the global ones

- id: T010
- title: Local skill copies that shadow the global ones
- category: tooling
- priority: P3
- priority-reason: Reconciliation of porting_liferay set aside by the owner (install from the shared repos); only the two stale conflict-resolver copies here remain
- next-up: no
- state: waiting
- executor: user-decision
- depends-on: -
- decider: owner: delete the two stale copies in this workspace; and who reconciles porting_liferay's local skills with gcube-ai-toolkit
- sources: conversation of 2026-10-08; tasks/tooling/notes/porting-liferay-skill-additions-2026-10-08.md
- paths: ai-coding-tools/.kilo/skills/{conflict-resolver,kilo-mcp-conflict-resolver}; ~/works/gcube/porting_liferay/.claude/skills, .kilo/skills
- handoff: Read tasks/tooling/T010-local-skill-copies.md, do the open steps, run the Verification, update the task and the registry.

## Goal

No stale project-level copy overrides a global skill.

## Steps

1. Delete stale copies.

## Verification

- Shadowing report is clean.
