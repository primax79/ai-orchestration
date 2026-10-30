# T088 Quattro test rossi su main: duplicati skill non fixable, kill dei discendenti su Linux, runaway stub lento

- id: T088
- title: Quattro test rossi su main: duplicati skill non fixable, kill dei discendenti su Linux, runaway stub lento
- category: engine
- priority: P1
- priority-reason: Suite rossa su main: maschera le regressioni degli executor dell'iniziativa 19
- next-up: no
- state: verified
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/orchestration_env.py, scripts/orchestration_invoke.py, scripts/orchestration_orchestrator.py, scripts/test_orchestration_*.py
- handoff: Read tasks/engine/T088-quattro-test-rossi-su-main-duplicati-skill-non-fix.md, do the open steps, run the Verification, update the task and the registry.
- verifier: codex
- kind: fix
- short: Test rossi su main

## Goal

Riportare verde la suite completa. Baseline 2026-10-29 su alf_ubuntu (uvx pytest ./scripts ./plugins): 4 failed, 635 passed. Su Mac e Linux: test_orchestration_env.py::test_duplicate_name_reserialized_frontmatter_resolves_to_trash e ::test_duplicate_name_folded_description_and_whitespace_resolves_to_trash (fixable False invece di True, righe 2607 e 2678); test_orchestration_orchestrator.py::test_bounds_kill_runaway_stub (6.2 s invece di < 5 s, riga 459). Solo Linux: test_orchestration_invoke.py::test_get_process_descendants_and_kill (kill ok False, riga 66). Trovare la causa nel codice (git log/blame per la regressione), correggere il codice o, solo se il test e' sbagliato, il test con motivazione; mai saltare test.

## Steps

- [ ] Riprodurre i quattro fallimenti singolarmente (Mac e Linux).
- [ ] Per ciascuno trovare il commit che lo ha introdotto (git log/blame) e la causa.
- [ ] Correggere il codice; correggere il test solo se è il test a essere sbagliato, motivandolo.

## Verification

- `uvx --quiet pytest -q -p no:cacheprovider ./scripts ./plugins` verde su alf_ubuntu (Linux).
- I tre test non legati a Linux verdi anche sul Mac.
- Nessun test saltato o rimosso.

## Log (newest first)

- 2026-10-30, codex: state `delivered` -> `verified` — OK: quarta verifica Codex PASS; su integration/19, non ancora su main
- 2026-10-30, kilo: state `in progress` -> `delivered` — fix 1396135, unito in integration/19
- 2026-10-30, orchestrator: state `bounced` -> `in progress` — terzo rinvio su alf_ubuntu
- 2026-10-30, codex: state `delivered` -> `bounced` — Terza verifica Codex NON OK: escape YAML e chiavi tra virgolette; richiesto sottoinsieme esplicito che fallisce chiuso
- 2026-10-30, kilo: state `in progress` -> `delivered` — fix 9d45091, unito in integration/19
- 2026-10-30, orchestrator: state `bounced` -> `in progress` — secondo rinvio allo stesso executor su alf_ubuntu
- 2026-10-30, codex: state `delivered` -> `bounced` — Seconda verifica Codex NON OK: B1 parziale (vedi nota di verifica)
- 2026-10-30, kilo: state `in progress` -> `delivered` — fix dopo la verifica, unito in integration/19
- 2026-10-30, orchestrator: state `bounced` -> `in progress` — rinviato allo stesso executor su alf_ubuntu con i rilievi
- 2026-10-30, codex: state `delivered` -> `bounced` — Verifica Codex NON OK: vedi tasks/engine/notes/T088-verification-codex.md
- 2026-10-30, kilo: state `in progress` -> `delivered` — commit su kilo/<slug>, unito in integration/19 dalla chain (test verdi a parte la baseline)
- 2026-10-29, orchestrator: state `open` -> `in progress` — kilo (gemini-4-argon) in screen su alf_ubuntu
