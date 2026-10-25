# T065 Use-case localized Italian section headings, --criteria option, and Italian stop-word short titles

- id: T065
- title: Use-case localized Italian section headings, --criteria option, and Italian stop-word short titles
- category: engine
- priority: P2
- priority-reason: Italian workspaces need localized UC headings, acceptance criteria on create, and clean short titles
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/to-analyze/20261025-172456-use-cases-localized-section-headings/note.md
- paths: -
- handoff: Read tasks/engine/T065-use-case-localized-italian-section-headings-criter.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: Use-case localized Italian section

## Goal

dave_agent writes tasks in Italian. Use-case files (tasks/use-cases/UC*.md) get fixed English section headings from 'use-cases create' (Description & Business Value, Preconditions, Scenario / Interaction Steps, Automated Verification Command, Acceptance Criteria, AI Validation Log), and the engine reads them by those exact names (tasks_engine.py _extract_section around line 6522; record-validation appends to '## AI Validation Log'). Translating them breaks show/validate/record-validation. Workaround in dave_agent: keep the engine files, render an Italian document with scripts/render_use_cases_it.py. Request: accept localized aliases (e.g. Descrizione, Precondizioni, Scenario, Comando di verifica, Criteri di accettazione, Registro delle verifiche) when parsing, and a per-workspace language setting for the generated template. Also: create has no option for acceptance criteria (always the generic '- [ ] Core flow works as expected.'), and the derived short title cuts mid-phrase ('Tenere una cartella del').

## Steps

- [x] Support Italian heading aliases, `--lang it`, `--criteria`, and Italian stop words in `derive_short_title`.

## Verification

- [x] `pytest plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py -k test_t057_t061_t062_t063_t052_and_n064`

## Log (newest first)

- 2026-10-25, owner: state `verified` -> `done` — Implemented and verified with automated pytest regression tests
- 2026-10-25, owner: state `delivered` -> `verified` — Implemented and verified with automated pytest regression tests
- 2026-10-25, kilo: state `in progress` -> `delivered`
- 2026-10-25, kilo: state `open` -> `in progress`
