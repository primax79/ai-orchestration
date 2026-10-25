# N064 use cases: localized section headings

- id: N064
- title: use cases: localized section headings
- kind: feature
- status: ready
- created: 2026-10-25T17:24:56.011450+00:00
- author: dave_agent
- about: -
- produced: -
- processed-by: -
- short: use cases localized section

dave_agent writes tasks in Italian. Use-case files (tasks/use-cases/UC*.md) get fixed English section headings from 'use-cases create' (Description & Business Value, Preconditions, Scenario / Interaction Steps, Automated Verification Command, Acceptance Criteria, AI Validation Log), and the engine reads them by those exact names (tasks_engine.py _extract_section around line 6522; record-validation appends to '## AI Validation Log'). Translating them breaks show/validate/record-validation. Workaround in dave_agent: keep the engine files, render an Italian document with scripts/render_use_cases_it.py. Request: accept localized aliases (e.g. Descrizione, Precondizioni, Scenario, Comando di verifica, Criteri di accettazione, Registro delle verifiche) when parsing, and a per-workspace language setting for the generated template. Also: create has no option for acceptance criteria (always the generic '- [ ] Core flow works as expected.'), and the derived short title cuts mid-phrase ('Tenere una cartella del').

---
- Author: dave_agent
- Workspace: /Users/Alfredo/works/dave_agent
- ai-orch: 1.1.0 (aed1caa)
- Date: 2026-10-25 17:24:55 UTC
