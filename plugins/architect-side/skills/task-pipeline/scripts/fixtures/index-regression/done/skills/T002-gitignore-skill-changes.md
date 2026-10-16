# T002 Uncommitted gitignore skill changes

- id: T002
- title: Uncommitted gitignore skill changes
- category: skills
- priority: P2
- priority-reason: Blocks a clean working tree in agentic-coding-kit, but ownership is unknown
- next-up: no
- state: done
- executor: user-decision
- depends-on: -
- decider: owner: whose are these changes, commit or discard?
- sources: status/handoff-2026-10-08-emergent-tasks-convention.md (Open 2)
- paths: agentic-coding-kit/plugins/common-tools/skills/gitignore/{SKILL.md,config/templates.json,scripts/generate_gitignore.py}; ~/.kilo/marketplaces/acp
- handoff: Ask the owner the question in Decider, record the answer here, update tasks/00-INDEX.md.

## Goal

Resolve uncommitted edits to gitignore.

## Steps

1. Ask owner and commit or discard.

## Verification

- Clean git status.
