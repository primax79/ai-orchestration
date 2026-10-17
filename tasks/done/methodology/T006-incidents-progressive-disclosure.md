# T006 Extract incident narratives to `references/incidents.md` (progressive disclosure)

- id: T006
- title: Extract incident narratives to references/incidents.md (progressive disclosure)
- category: methodology
- priority: P3
- priority-reason: Reduces skill activation token footprint without changing operational behavior
- next-up: no
- state: done
- executor: self
- depends-on: T003
- decider: -
- sources: ../architect-executor-consolidated-review.md (§1.4, Tier 3), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/, ../kilo-mcp/bindings/orchestration-methodology.json
- handoff: Read tasks/methodology/T006-incidents-progressive-disclosure.md, do the open steps, run the Verification, update the task and the registry.
- verifier: orchestrator:deep-reasoning

## Goal

Keep concise imperative rules in `orchestration-methodology/SKILL.template.md` while moving the multi-sentence live incident narratives and domain-specific examples (JPA annotations, `.ts` files) into `references/incidents.md`.

## Steps

1. Measure before-byte/token count of `orchestration-methodology/SKILL.md` and `kilo-mcp-orchestrator/SKILL.md`.
2. Create `references/incidents.md` under `orchestration-methodology` (and mirror or link cleanly for `kilo-mcp-orchestrator`), keeping 1-2 line imperative rules in `SKILL.template.md`.
3. Regenerate generic and bound skills and record the before/after token reduction.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` exits 0, and every operational rule remains present in `SKILL.md`.
