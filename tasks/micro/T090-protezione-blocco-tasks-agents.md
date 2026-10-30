# T090 tasks upgrade: proteggere le modifiche dell'utente nel blocco gestito di tasks/AGENTS.md

- id: T090
- title: tasks upgrade: proteggere le modifiche dell'utente nel blocco gestito di tasks/AGENTS.md
- kind: fix
- priority: P2
- state: in progress
- executor: kilo
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, scripts/orchestration_env.py
- depends-on: -
- size: S
- labels: upgrade, safety
- short: Protezione blocco tasks/AGENTS

## What

Emerged from the Codex verification of 19.3, round 3 (`tasks/19-multi-machine-development/notes/19.3-verification-codex.md`).

`render_upgraded_agents_md` (`tasks_engine.py:708-726`), which `tasks upgrade` and `ai-orch upgrade` call (`orchestration_env.py:9955-9968`), always replaces the managed block of `tasks/AGENTS.md`. Any user edits inside the markers are lost without warning.

Align it with the rule already in place for the root AGENTS.md (19.3):

- replace the managed block only if its content matches the current rendering or a historical one, exactly after whitespace normalization;
- otherwise keep it, report it for manual review, and do not apply the upgrade to that block.

Add a test with a user edit inside the block, and a test showing that an unmodified block is still updated normally.

## Log (newest first)

- 2026-10-30, orchestrator: state `open` -> `in progress` — kilo (gemini-4-argon) come utente kilo su alf_ubuntu, /srv/agents, base integration/19 — primo executor con utente agenti
