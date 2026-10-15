# T003 Phase 5 explicit decision point and worktree lifecycle closure

- id: T003
- title: Phase 5 explicit decision point and worktree lifecycle closure
- category: methodology
- priority: P1
- priority-reason: Interactive orchestrators lack the explicit merge/fix-inline/bounce/ask criteria and leave orphan worktrees on cancel
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§2.2, §2.7), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md, ../kilo-mcp/bindings/orchestration-methodology.json, ../kilo-mcp/plugins/architect-side/agents/mcp-orchestrator-agent.md
- handoff: Read tasks/methodology/T003-phase5-decision-and-worktree-cleanup.md, do the open steps, run the Verification, update the task and the registry.
- verifier: orchestrator:deep-reasoning

## Goal

Promote the explicit post-verification decision criteria (`merge` / `fix inline` / `bounce via continue_session_id` / `stop and ask user`) into Phase 5 of `orchestration-methodology`, define worktree cleanup for every terminal state (including `cancelled` and `discarded`), and scope Phase 1 model/auth checks to once per session or after failure.

## Steps

1. Edit `../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md` and `../kilo-mcp/bindings/orchestration-methodology.json`:
   - Scope Phase 1 engine/model/auth check to once per session or after a dispatch failure.
   - Add the explicit 4-way decision table at the end of Phase 5.
   - In Phase 4 & Phase 6, specify worktree/branch cleanup (`git worktree remove` + branch disposition) for cancelled and discarded runs, not only merged runs.
2. Regenerate generic and bound skills (`regenerate_generic_skills.py`, `regenerate_bound_skills.py`) and indices.

## Verification

- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` exits 0.
- `python3 ../ai-architect-executor/plugins/shared/skills/interactive-role-setup/scripts/validate_roles.py --plugin-dir ../ai-architect-executor/plugins/architect-side --plugin-dir ../ai-architect-executor/plugins/executor-side --plugin-dir ../ai-architect-executor/plugins/shared` exits 0.
