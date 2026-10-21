# T044 Durable verification requests addressed to a workspace or session

- id: T044
- title: Durable verification requests addressed to a workspace or session
- category: engine
- priority: P1
- priority-reason: Validation by requesters is the owner's rule, but requests sent as session messages are lost when a session closes (two of four lost on 2026-10-21)
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: owner 2026-10-21 (validation by requester; 'use something like questions'); method 0.17 (verification queue drained at session start); inbox N046 (gcube_atlas handover: Kilo/Gemini sessions cannot receive cross-session messages)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, skills
- handoff: Read tasks/engine/T044-durable-verification-requests-addressed-to-a-works.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: gcube_atlas
- short: Durable verification requests

verification pending: run Verification checks (verify-by: gcube_atlas)

## Goal

A delivered task can carry a 'verify-by: <workspace or session>' request with what to check, set by a command; 'ai-orch tasks verification-queue [--for <workspace>]' lists the requests addressed to the caller's workspace across registered workspaces; the index and the UIs show them; the skills tell every session to drain its queue at session start (method 0.17) and answer with transition verified --verifier or a NOT OK note.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.

## Log (newest first)

- 2026-10-21, ai-coding-tools: state `in progress` -> `delivered` — Merged T044; durable verify-by and verification-queue across workspaces verified
- 2026-10-21, ai-coding-tools: state `open` -> `in progress` — Dispatching T044 (Durable verification requests addressed to a workspace or session) to Kilo
