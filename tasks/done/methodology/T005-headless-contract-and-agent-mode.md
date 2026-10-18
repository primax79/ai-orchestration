# T005 Hardening `headless-executor-contract` and evaluating Kilo agent mode

- id: T005
- title: Hardening headless-executor-contract and evaluating Kilo agent mode
- category: methodology
- priority: P2
- priority-reason: Executor contract lacks explicit 1-task-1-commit and worktree blast-radius rules; delivery channel via skills_to_load needs verification
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§2.3, §4.3, §4.4), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/executor-side/skills/headless-executor-contract/SKILL.template.md, ../kilo-mcp/bindings/headless-executor-contract.json
- handoff: Read tasks/methodology/T005-headless-contract-and-agent-mode.md, do the open steps, run the Verification, update the task and the registry.
- verifier: orchestrator:deep-reasoning
- short: Executor contract hardening

## Goal

Add the missing commit-scope, isolation blast-radius, exact `Final Report` skeleton, and reproducible verification-command rules to `headless-executor-contract`, and check `metrics.jsonl` / task records to decide whether a dedicated `headless-executor` Kilo agent definition is warranted.

## Steps

1. Update `../ai-architect-executor/plugins/executor-side/skills/headless-executor-contract/SKILL.template.md` and `../kilo-mcp/bindings/headless-executor-contract.json`:
   - Add explicit rule: commit at task end, scoped strictly to this task's changes ("one task, one commit").
   - Add explicit isolation blast-radius rule: never leave `working_directory`, never touch sibling worktrees or the main checkout.
   - Include the exact Markdown skeleton expected for `Final Report` (`Outcome`, `Files changed`, `Verification` with exact command + output, `Issues`).
2. Inspect `KILO_MCP_DATA_DIR` (`metrics.jsonl` / task records) to check whether `skills_to_load` is populated in real delegations and decide on the `headless-executor` agent mode (§4.4) and Executor skill authoring guide (§4.3).
3. Regenerate generic and bound skills and indices.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` exits 0.
