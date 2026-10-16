# Task Index

Live registry of work for this workspace. Convention: [`AGENTS.md`](AGENTS.md). History (hand-offs): [`../status/`](../status/).

## Next up

| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
| T013 | P1 | [`ai-orchestration`: formal task model and orchestration Web/VSCode UI](tooling/T013-ai-orchestration-project.md) | self | `Read ai-orchestration/tasks/00-INDEX.md and ai-orchestration/docs/03-task-model-and-ui-architecture.md, work the next open task in ai-orchestration, and mirror state changes here.` |
| T003 | P2 | [Docs consistency for emergent tasks](skills/T003-docs-consistency.md) | self | `Read tasks/skills/T003-docs-consistency.md, do the open steps, update the task and this index.` |
| T004 | P2 | [Old skill name references](tooling/T004-old-name-references.md) | self | `Read tasks/tooling/T004-old-name-references.md, do the open steps, update the task and this index.` |

## Tasks by category

### skills

Changes to the skills of the sub-repositories. Owner session: unassigned ([README](skills/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T003 | P2 | [Docs consistency for emergent tasks](skills/T003-docs-consistency.md) | open | self | - |
| T011 | P2 | [Unify the gCube documentation-alignment skills and agent into one skill (gcube-repo-standards)](skills/T011-gcube-doc-alignment-unification/README.md) | verified | dedicated-session | - |

### tooling

Installations, Kilo/Claude configuration. Owner session: unassigned ([README](tooling/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T004 | P2 | [Old skill name references](tooling/T004-old-name-references.md) | open | self | - |
| T010 | P3 | [Local skill copies that shadow the global ones](tooling/T010-local-skill-copies.md) | waiting | user-decision | - |
| T012 | P2 | [ai-swissknife CLI: capabilities for skill maintenance](tooling/T012-swissknife-cli-capabilities.md) | open | dedicated-session | - |
| T013 | P1 | [`ai-orchestration`: formal task model and orchestration Web/VSCode UI](tooling/T013-ai-orchestration-project.md) | open | self | - |

### investigations

Items of the former `status/open-investigations.md`. Owner session: unassigned ([README](investigations/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T006 | P3 | [Pi as second Executor binding](investigations/T006-pi-executor-binding.md) | open | self | - |
| T007 | P3 | [toolkit-release-manager generalization](investigations/T007-release-manager-generalization.md) | waiting | user-decision | - |
| T008 | P3 | [references/ reorganization](investigations/T008-references-reorganization.md) | open | self | - |
| T009 | P3 | [Canonical home for instructions/](investigations/T009-instructions-home.md) | waiting | user-decision | - |

## Decisions waiting

Priorities validated 2026-10-08 against the P0-P3 criteria (no P0: no security exposure, no release blocked). Recommendations are the agent's; the decider confirms.

| Task | Question (exact) | Decider | Blocks |
| --- | --- | --- | --- |
| T007 | One shared config-driven release-manager tool (where does it live?) or accept the per-repo duplication? Recommendation: keep duplication until a fifth copy appears. | owner | - |
| T009 | Move `adk-agentic-coding-kit/instructions/` to `agentic-coding-kit`, or leave it? Recommendation: move (content is generic). | owner | - |

## Done

| Id | Task | Result | Closed |
| --- | --- | --- | --- |
| T002 | [Uncommitted gitignore skill changes](done/skills/T002-gitignore-skill-changes.md) | done (committed and pushed, common-tools 0.3.1) | 2026-10-08 |
| T001 | [Apply lr74 review corrections](done/skills/T001-apply-lr74-corrections.md) | done (confirmed by lr74-handover-e-audit-auth) | 2026-10-08 |
| T005 | [Align keycloak-openid-federation to new convention](done/tooling/T005-keycloak-convention.md) | done | 2026-10-08 |
