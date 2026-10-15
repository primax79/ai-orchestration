# T010 Core skill renames decision (`docs/06` taxonomy vs. current skill names)

- id: T010
- title: Core skill renames decision (docs/06 taxonomy vs. current skill names)
- category: methodology
- priority: P2
- priority-reason: Owner decision needed on whether to rename core skills (e.g. macroplan-authoring -> task-pipeline) before committing or defer to avoid churn
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: tasks/_reviews/2026-10-15-coherence-review-from-claude.md (F5), docs/06-naming-taxonomy-and-coherence.md
- paths: docs/06-naming-taxonomy-and-coherence.md, plugins/, ../kilo-mcp/bindings/
- handoff: Read docs/06-naming-taxonomy-and-coherence.md and tasks/methodology/T010-core-skill-naming-decision.md, record the owner's decision on whether to execute or defer the core skill renames, and update the registry.
- verifier: owner

## Goal

Decide whether to execute the core skill renames proposed in `docs/06-naming-taxonomy-and-coherence.md` §2.1 (`macroplan-authoring` → `task-pipeline`, `interactive-role-setup` → `orchestration-setup`, `delegation-roi-analysis` → `orchestration-metrics`, `task-delegation` → `task-worktree-ops`, `headless-executor-contract` → `executor-contract`) before committing, or defer them and keep the current names. (Note: the `kilo-mcp-*` prefix alignment in `../kilo-mcp` §2.2 is already applied).

## Steps

1. Confirm with the owner whether to execute the `docs/06` §2.1 core skill renames now or defer them.
2. If deferred: mark §2.1 in `docs/06-naming-taxonomy-and-coherence.md` as deferred/future and close this task.
3. If approved: rename the skill directories, frontmatter `name` fields, `skill-requirements.json`, `regenerate_generic_skills.py`, and `../kilo-mcp/scripts/regenerate_bound_skills.py` mappings, then regenerate and verify.

## Verification

- `./bin/ai-orch config validate --plugin-dir ./plugins/architect-side --plugin-dir ./plugins/executor-side --plugin-dir ./plugins/shared` exits 0.
- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` exits 0.
