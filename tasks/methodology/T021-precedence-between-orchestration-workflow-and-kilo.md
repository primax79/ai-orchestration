# T021 Precedence between orchestration-workflow and kilo-mcp-orchestrator; fix binding template drift

- id: T021
- title: Precedence between orchestration-workflow and kilo-mcp-orchestrator; fix binding template drift
- category: methodology
- priority: P2
- priority-reason: Owner's open answer to Q003; T018 shows the bound skill lost verification modes, decision table and state table
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: plugins/architect-side/skills/orchestration-workflow/, ../kilo-mcp/bindings/orchestration-workflow.json, ../kilo-mcp/plugins/architect-side/skills/kilo-mcp-orchestrator/
- handoff: Read tasks/methodology/T021-precedence-between-orchestration-workflow-and-kilo.md, do the open steps, run the Verification, update the task and the registry.
- short: Binding template drift

verification pending: run Verification checks (independent verifier)

## Goal

Implement tasks/env-doctor/notes/T018-precedence-analysis.md sections 4 and 5: reciprocal precedence text in both skills, non-competing descriptions, keep verification modes / post-verification decision table / state table / scaffolding check in the bound skill (template not overridden), health-check cadence, wait-vs-detached note, and the dispatch-state rule (in progress before dispatch, delivered on Final Report) in the binding so regeneration keeps it.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
