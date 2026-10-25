# T053 Make test_confirm_start_run_hash_mismatch_if_plan_changed deterministic

- id: T053
- title: Make test_confirm_start_run_hash_mismatch_if_plan_changed deterministic
- category: engine
- priority: P2
- priority-reason: A flaky test hides real failures and blocks gated merges
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N054
- paths: scripts/test_orchestration_triggers.py, scripts/orchestration_triggers.py
- handoff: Read tasks/engine/T053-make-test-confirm-start-run-hash-mismatch-if-plan.md, do the open steps, run the Verification, update the task and the registry.
- short: Flaky trigger test

## Goal

The test passes deterministically under load: find the timing assumption behind 'preview_failed' (seen once in a 32-minute suite run, passes alone), fix the test or the code, and prove it with 20 consecutive runs under a CPU stress (e.g. running it in parallel with other tests). Same for scripts/test_orchestration_runs.py::test_t022_cancel_stops_tool_children_in_new_session (failed once in a 13-minute full run on 2026-10-25, passes alone 6/6 on main and on a branch): likely a process-kill timing assumption. Root cause found for the trigger tests (2026-10-25): they call the real `kilo` CLI for a version check with a 5 s timeout ('Run preview failed: Version check timed out (5s) for kilo'), which expires when many Kilo runs load the machine; test_confirm_start_run_starts_stub_run failed the same way. Tests must stub the CLI version check (no real `kilo` subprocess in unit tests).

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
