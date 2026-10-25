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

The test passes deterministically under load: find the timing assumption behind 'preview_failed' (seen once in a 32-minute suite run, passes alone), fix the test or the code, and prove it with 20 consecutive runs under a CPU stress (e.g. running it in parallel with other tests).

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
