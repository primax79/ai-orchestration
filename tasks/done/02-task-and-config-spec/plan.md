# 02 - Formal Task Model, State Machine & `orchestration.toml` Specification

> **Derived from specs:** [`../specs/task-and-state-model.md`](../../specs/task-and-state-model.md), [`../specs/orchestration-config-and-agents-md.md`](../../specs/orchestration-config-and-agents-md.md)

## Tasks

### 02.1 - Align `macroplan-authoring` and `orchestration-methodology` with the Unified Task & Verification Spec
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15)
- **Focus files:** `tasks/specs/task-and-state-model.md`, `plugins/architect-side/skills/macroplan-authoring/SKILL.md`, `plugins/architect-side/skills/macroplan-authoring/references/template.md`, `plugins/architect-side/skills/orchestration-methodology/SKILL.template.md`
- **Steps:**
  1. Update `macroplan-authoring/SKILL.md` and `references/template.md` to include the unified state machine (`bounced` transition, optional `profile`, `verification-mode: self | cross-agent | panel | owner`, `verifier` fields after `handoff`).
  2. Update `orchestration-methodology/SKILL.template.md` ("Track task state as a path, not a label") so its state table matches `tasks/specs/task-and-state-model.md` and explicitly documents optional cross-agent / multi-engine panel verification on `delivered → verified`.
  3. Regenerate generic skills (`scripts/regenerate_generic_skills.py`) and indices (`scripts/generate_skill_indices.py`).
- **Verification:**
  - `python3 scripts/regenerate_generic_skills.py && python3 scripts/generate_skill_indices.py` exits 0.
- **Commit:** Single commit scoped to `02.1`.
