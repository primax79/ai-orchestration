# T045 Broker follow-ups from validation: mcp --local, stable error codes, project field

- id: T045
- title: Broker follow-ups from validation: mcp --local, stable error codes, project field
- category: server-and-bindings
- priority: P1
- priority-reason: 16.5 failed validation on its promised in-process mode; error contract deviates from spec 3b
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N042, N045 (d4science-python-library validation of 16.5)
- paths: bin/ai-orch, ../ai-orchestration-ui/backend/broker/
- handoff: Read tasks/server-and-bindings/T045-broker-follow-ups-from-validation-mcp-local-stable.md, do the open steps, run the Verification, update the task and the registry.
- short: Broker validation follow-ups

## Goal

'ai-orch mcp --local' serves the broker tools in-process (no broker process) as 16.5 promised; every broker error carries a stable kebab-case 'error' code (e.g. hash-mismatch) and a readable 'message' (no raw CLI JSON); tasks.next and questions.list items carry 'project', and workspace-level next distinguishes _workspace items.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
