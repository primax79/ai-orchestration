# T053 Make test_confirm_start_run_hash_mismatch_if_plan_changed deterministic

- id: T053
- title: Make test_confirm_start_run_hash_mismatch_if_plan_changed deterministic
- category: engine
- priority: P2
- priority-reason: A flaky test hides real failures and blocks gated merges
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N054
- paths: conftest.py, scripts/orchestration_runs.py, scripts/orchestration_env.py, scripts/test_orchestration_triggers.py, scripts/test_orchestration_runs.py, scripts/test_orchestration_env.py, scripts/test_orchestration_invoke.py, scripts/test_orchestration_orchestrator.py, plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py
- handoff: Read tasks/engine/T053-make-test-confirm-start-run-hash-mismatch-if-plan.md, do the open steps, run the Verification, update the task and the registry.
- verifier: ai-coding-tools-c1
- short: Flaky trigger test

## Goal

The test passes deterministically under load: find the timing assumption behind 'preview_failed' (seen once in a 32-minute suite run, passes alone), fix the test or the code, and prove it with 20 consecutive runs under a CPU stress (e.g. running it in parallel with other tests). Same for scripts/test_orchestration_runs.py::test_t022_cancel_stops_tool_children_in_new_session (failed once in a 13-minute full run on 2026-10-25, passes alone 6/6 on main and on a branch): likely a process-kill timing assumption. Root cause found for the trigger tests (2026-10-25): they call the real `kilo` CLI for a version check with a 5 s timeout ('Run preview failed: Version check timed out (5s) for kilo'), which expires when many Kilo runs load the machine; test_confirm_start_run_starts_stub_run failed the same way. Tests must stub the CLI version check (no real `kilo` subprocess in unit tests).

## Steps

- [x] Stub CLI version checks in `conftest.py` (`AI_ORCH_TEST_CLI_VERSIONS`) and honor the override in `scripts/orchestration_runs.py` (`_default_cli_version_probe` / `check_tool_availability`) and `scripts/orchestration_env.py` (`check_cli_binary`), plus add autouse fake CLI fixtures in `scripts/test_orchestration_triggers.py`, `scripts/test_orchestration_env.py`, and `plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py` so no unit test spawns the real `kilo`/`claude`/`codex` binaries (with explicit opt-out test `test_tool_availability_default_version_probe_with_fake_binary`).
- [x] Replace fixed 5 s waits in `scripts/test_orchestration_runs.py::test_t022_cancel_stops_tool_children_in_new_session` (and sibling cancel/invoke/trigger/orchestrator tests) with 30 s polling that waits for both the grandchild PID file and the supervisor's `agent` record (`pid`, `pgid`, `start_time`) before calling `run cancel`, and polls up to 30 s for process termination.
- [x] Run each of the three tests 20 times in a row under 8-worker CPU stress, verify with poison CLIs (`exit 99`) first on `PATH`, and run the full test suite.

## Verification

- 20x consecutive runs under 8-CPU stress (`python3 -c "while True: pass"` x 8):
  - `scripts/test_orchestration_triggers.py::test_confirm_start_run_hash_mismatch_if_plan_changed`: `20/20 passed`
  - `scripts/test_orchestration_triggers.py::test_confirm_start_run_starts_stub_run`: `20/20 passed`
  - `scripts/test_orchestration_runs.py::test_t022_cancel_stops_tool_children_in_new_session`: `20/20 passed`
- Poison CLI check (fake `kilo`, `claude`, `codex` exiting 99 first on `PATH`):
  - `PATH="/tmp/poison-bin:$PATH" ~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/test_orchestration_triggers.py scripts/test_orchestration_env.py plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py` -> `27 passed`, `81 passed`, `37 passed`.
- Full test suite:
  - `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/` -> `579 passed in 337.82s`.

## Log

- 2026-10-25, ai-coding-tools-c1: state `verified` -> `done`
- 2026-10-25, ai-coding-tools-c1: state `delivered` -> `verified`
- 2026-10-25, kilo: state `open` -> `delivered` — stubbed CLI version probes and replaced fixed cancel/startup waits with 30s condition polling; 20/20 stress runs and full suite (579 tests) green.
