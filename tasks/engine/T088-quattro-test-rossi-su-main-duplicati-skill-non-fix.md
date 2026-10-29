# T088 Quattro test rossi su main: duplicati skill non fixable, kill dei discendenti su Linux, runaway stub lento

- id: T088
- title: Quattro test rossi su main: duplicati skill non fixable, kill dei discendenti su Linux, runaway stub lento
- category: engine
- priority: P1
- priority-reason: Suite rossa su main: maschera le regressioni degli executor dell'iniziativa 19
- next-up: no
- state: in progress
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/orchestration_env.py, scripts/orchestration_invoke.py, scripts/orchestration_orchestrator.py, scripts/test_orchestration_*.py
- handoff: Read tasks/engine/T088-quattro-test-rossi-su-main-duplicati-skill-non-fix.md, do the open steps, run the Verification, update the task and the registry.
- kind: fix
- short: Test rossi su main

## Goal

Riportare verde la suite completa. Baseline 2026-10-29 su alf_ubuntu (uvx pytest ./scripts ./plugins): 4 failed, 635 passed. Su Mac e Linux: test_orchestration_env.py::test_duplicate_name_reserialized_frontmatter_resolves_to_trash e ::test_duplicate_name_folded_description_and_whitespace_resolves_to_trash (fixable False invece di True, righe 2607 e 2678); test_orchestration_orchestrator.py::test_bounds_kill_runaway_stub (6.2 s invece di < 5 s, riga 459). Solo Linux: test_orchestration_invoke.py::test_get_process_descendants_and_kill (kill ok False, riga 66). Trovare la causa nel codice (git log/blame per la regressione), correggere il codice o, solo se il test e' sbagliato, il test con motivazione; mai saltare test.

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion

## Log (newest first)

- 2026-10-29, orchestrator: state `open` -> `in progress` — kilo (gemini-4-argon) in screen su alf_ubuntu
