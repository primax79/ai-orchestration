# T011 Unify the gCube documentation-alignment skills and agent into one skill

- id: T011
- title: Unify the gCube documentation-alignment skills and agent into one skill
- category: skills
- priority: P2
- priority-reason: Seven artifacts (six skills and one agent) for one job, with duplicated template-fetch logic and no script; they compete for the same trigger and must be kept aligned by hand. Not on any critical path.
- next-up: no
- state: verified
- executor: dedicated-session
- depends-on: -
- decider: owner (transition period for the old skill names, see Decision gate)
- sources: analysis of 2026-10-08 in the porting_liferay session (sizes, shared passages, references); gcube-ai-toolkit AGENTS.md rules A, C, D
- paths: gcube-ai-toolkit/plugins/gcube-developer-tools, gcube-ai-toolkit/_attic, gcube-ai-toolkit/docs, gcube-ai-toolkit/.claude-plugin, gcube-ai-toolkit/CHANGELOG.md, gcube-ai-toolkit/scripts
- handoff: Leggi tasks/skills/T011-gcube-doc-alignment-unification/README.md, poi CONTEXT.md e il registro dei task, esegui il task T011 senza committare né pushare, aggiorna PROGRESS.md e il registro.

## Goal

One skill, gcube-doc-generator, in the plugin gcube-developer-tools.

## Steps

1. Inventory the artifacts.

## Verification

- Scripts pass.
