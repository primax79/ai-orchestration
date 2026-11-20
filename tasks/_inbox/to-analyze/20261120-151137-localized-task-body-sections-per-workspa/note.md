# N099 Localized task body sections per workspace (Italian tasks fail validate)

- id: N099
- title: Localized task body sections per workspace (Italian tasks fail validate)
- kind: request
- status: ready
- created: 2026-11-20T15:11:37.339946+00:00
- author: porting_liferay
- about: T092
- produced: -
- processed-by: -
- short: Localized task body sections

validate requires English body sections (## Goal, ## Steps, ## Verification); porting_liferay translated its task files
to Italian on 2026-11-19 (owner rule), sections are "## Obiettivo", "## Passi", "## Verifica", so engine 0.8.20 reports
97 "missing required Markdown section(s)" FAILs. Input for T092 (per-workspace customisation): allow a workspace to map
section names (and possibly state words) to the canonical ones, e.g. in orchestration.toml or tasks/AGENTS.md front
matter. Also: delivered/verified logic that reads "## Verification" should use the mapped name.

---
- Author: porting_liferay
- Workspace: /Users/Alfredo/works/gcube/porting_liferay
- ai-orch: 1.1.0 (fee3a35)
- Date: 2026-11-20 15:11:37 UTC
