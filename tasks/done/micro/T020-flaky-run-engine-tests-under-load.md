# T020 Flaky run-engine tests under load

- id: T020
- title: Flaky run-engine tests under load
- category: micro
- priority: P2
- priority-reason: Red runs mask real regressions; seen during 07.12, 09.4 and the 11.1 merge
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/test_orchestration_runs.py, scripts/orchestration_runs.py
- handoff: Read tasks/micro/T020-flaky-run-engine-tests-under-load.md, do the open steps, run the Verification, update the task and the registry.

## Goal

test_preview_side_effect_free (hash mismatch) and test_reconcile_pid_reuse_simulated_does_not_kill (process not alive) fail about once in two full runs of scripts/test_orchestration_runs.py, never in isolation. Find the root cause (shared state, timing, real PIDs) and make them deterministic without weakening what they check.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
