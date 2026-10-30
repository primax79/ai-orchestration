# T089 I test scrivono nella config globale reale: serve isolamento automatico in conftest

- id: T089
- title: I test scrivono nella config globale reale: serve isolamento automatico in conftest
- kind: bug
- priority: P1
- state: verified
- executor: kilo
- paths: conftest.py, scripts/test_*.py, plugins/*/skills/*/scripts/test_*.py
- depends-on: -
- size: S
- labels: tests
- short: Test non isolati

## What

**Evidence on alf_ubuntu (2026-10-30):**

- At 01:25:09 the suite run (by the chain, during the merge of 19.7) created `~/.config/ai-orchestration/projects/p/orchestration.toml`, a `[workspace]` block with `title = "p"` and `id = "p-1"`, in the user's REAL global config.
- At least one test registers a temporary project without isolating `AI_ORCHESTRATION_CONFIG` / `AI_ORCH_CONFIG_DIR` / `HOME`.
- Separately, the Codex verification of 19.16 found a fixture with real `~/works` paths that can write configuration into real projects.

**Fix:**

- Add an `autouse` fixture in the root `conftest.py` that, for every test, points `HOME`, `AI_ORCHESTRATION_CONFIG`, `AI_ORCH_CONFIG_DIR`, `XDG_CONFIG_HOME` and the kilo-mcp data dir to directories under `tmp_path`. Tests that need a different home keep overriding it.
- Add a guard test: after the session, nothing under the real `~/.config/ai-orchestration` or the real `~/works` has been created or modified. Compare against a snapshot of mtimes or listings taken at session start.
- Find and fix the test that writes the project `p`.
- Delete `~/.config/ai-orchestration/projects/p/` on alf_ubuntu after the fix. It is a test leftover with no value.

**Verification:** run the full suite twice in a row on the hub. `~/.config/ai-orchestration` must stay byte-identical, which you check with `find -newer` on a marker file.

## Log (newest first)

- 2026-10-30, codex+orchestrator: state `delivered` -> `verified` — OK con caveat: B1 e B3 risolti; B2 accettato dall'orchestratore (esclusioni generiche per prestazioni), vedi tasks/micro/notes/T089-verification-codex.md
- 2026-10-30, kilo: state `in progress` -> `delivered` — fix 9f99100, unito in integration/19
- 2026-10-30, orchestrator: state `bounced` -> `in progress` — rinviato su alf_ubuntu (19.6 dopo 19.5, 19.8 dopo 19.16)
- 2026-10-30, codex: state `delivered` -> `bounced` — Verifica Codex NON OK: vedi nota di verifica
- 2026-10-30, kilo: state `in progress` -> `delivered` — commit su kilo/<slug>, unito in integration/19 dalla chain
- 2026-10-30, orchestrator: state `open` -> `in progress` — kilo (gemini-3.8-flash) su alf_ubuntu, da integration/19
