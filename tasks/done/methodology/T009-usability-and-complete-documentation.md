# T009 Product & per-skill usability, quickstart playbook, and instruction clarity

- id: T009
- title: Product & per-skill usability, quickstart playbook, and instruction clarity
- category: methodology
- priority: P1
- priority-reason: Owner requirement: clear usability, documentation, and operational instructions both per-skill and for the complete orchestration product
- next-up: no
- state: done
- executor: kilo
- depends-on: 01.1, 01.2
- decider: -
- sources: conversation 2026-10-15 (owner explicit requirement)
- paths: README.md, docs/00-QUICKSTART-AND-PLAYBOOK.md, plugins/*/skills/*/SKILL.md, plugins/*/skills/*/SKILL.template.md
- handoff: Read tasks/methodology/T009-usability-and-complete-documentation.md and tasks/01-repo-consolidation/plan.md (01.3), write docs/00-QUICKSTART-AND-PLAYBOOK.md, overhaul README.md, and add Quick Reference headers to each skill, then run Verification and update the registry.
- verifier: orchestrator:deep-reasoning

## Goal

Provide end-to-end documentation, practical playbooks, and scannable per-skill instructions so both a human operator and an AI agent can configure, bootstrap, and run `ai-orchestration` (as a whole product and skill by skill) without friction.

## Steps

1. Write `docs/00-QUICKSTART-AND-PLAYBOOK.md` with step-by-step workflows explicitly covering both **Single-Framework Native Mode** (Kilo-only or Claude-only: task definition, acceptance criteria, parallel native worktrees/subagents, blind-subagent verification — zero MCP required) and **Multi-Framework MCP Mode** (delegating across `kilo-mcp` / `claude-mcp` / `codex`):
   - Global & project configuration (`orchestration.toml` + `AGENTS.md` generation for single-framework vs. multi-framework setups);
   - Choosing between inline delegation, Emergent Task (`T###`), and Initiative (`NN-<slug>`);
   - Delegating across channels (native `agent_manager`/`task` or Claude `Agent` vs. external MCP `kilo-mcp`/`claude-mcp` vs. manual CLI worktrees);
   - Running optional independent verification (`self`, `independent-session` within the same framework, `cross-agent` across frameworks, `panel`, `owner`);
   - Troubleshooting & script reference (`orchestration_config.py`, `tasks_engine.py`, `apply_fix_to_worktree.sh`).
2. Overhaul `README.md` so it explains the unified `ai-orchestration` product, its 3 plugins (`architect-side`, `executor-side`, `shared`), every skill's exact role, and how it connects to `kilo-mcp`, `claude-mcp`, and the upcoming UI.
3. Add a consistent **Quick Reference** section at the top of each skill (`Role`, `When to use`, `Companion scripts`, `Related skills`) and regenerate generic/bound skills and indices.

## Verification

- `python3 scripts/regenerate_generic_skills.py && python3 scripts/generate_skill_indices.py` exits 0.
- All relative links in `README.md` and `docs/00-QUICKSTART-AND-PLAYBOOK.md` resolve on disk.
