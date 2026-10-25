# T034 Tooling feedback built into the product: ai-orch feedback, skill rule, upgrade AGENTS.md

- id: T034
- title: Tooling feedback built into the product: ai-orch feedback, skill rule, upgrade AGENTS.md
- category: server-and-bindings
- priority: P1
- priority-reason: Owner 2026-10-21: every session using the tooling must report needs and improvements; the rule must live in the product, not in messages
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: owner request 2026-10-21; inbox N001-N024 (first feedback round)
- paths: bin/ai-orch, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/*/skills/*/SKILL.template.md, bindings
- handoff: Read tasks/server-and-bindings/T034-tooling-feedback-built-into-the-product-ai-orch-fe.md, do the open steps, run the Verification, update the task and the registry.
- verifier: gcube-atlas-83
- short: Built-in feedback channel

## Goal

A session in any workspace reports a need, defect or improvement about the tooling with one command (ai-orch feedback), which lands as an inbox note in the ai-orchestration project's own tasks tree wherever the tool is installed from; the generated skills and the AGENTS.md written by upgrade tell every session to do so, and the maintainers triage the notes into tasks.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.