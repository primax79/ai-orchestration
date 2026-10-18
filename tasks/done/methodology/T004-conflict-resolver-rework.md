# T004 Rework `conflict-resolver` for Architect audience and incompatible designs

- id: T004
- title: Rework conflict-resolver for Architect audience and incompatible designs
- category: methodology
- priority: P2
- priority-reason: Current stub targets the wrong role and tells the agent to preserve both sides even when designs are incompatible
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§2.5), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/architect-side/skills/conflict-resolver/SKILL.template.md, ../kilo-mcp/bindings/conflict-resolver.json
- handoff: Read tasks/methodology/T004-conflict-resolver-rework.md, do the open steps, run the Verification, update the task and the registry.
- verifier: orchestrator:deep-reasoning
- short: Conflict-resolver rework

## Goal

Rewrite `conflict-resolver` (`SKILL.template.md` + `kilo-mcp` binding) so it addresses the Architect at Phase 6 merge time, separates mechanical conflicts from incompatible-design conflicts, and requires running the test suites of both features plus logging recurring conflicts as decomposition telemetry.

## Steps

1. Update `../ai-architect-executor/plugins/architect-side/skills/conflict-resolver/SKILL.template.md` and `../kilo-mcp/bindings/conflict-resolver.json`:
   - Re-target prose to the Architect performing Phase 6 integration.
   - Add the primary fork: **mechanical conflict** (imports, barrel exports, adjacent registrations → combine both) vs. **incompatible design/signature conflict** (stop, choose one design, bounce the other task back to its session or ask the user).
   - Require running the test suites of **both** involved features plus consuming-app build after resolution.
   - Instruct logging non-trivial conflicts as decomposition telemetry (`kilo_log_issue`).
2. Regenerate generic and bound skills and indices.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` exits 0.
