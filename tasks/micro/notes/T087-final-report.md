# Final Report: T087 ai-orch describe elenca solo una parte dei sottocomandi di run

- **Outcome:** delivered.
- **Files changed:**
  - `bin/ai-orch`: dynamically populate `CLI_DESCRIPTION["commands"]["run"]["subcommands"]` from `orchestration_runs.get_subcommands_description()`.
  - `scripts/orchestration_runs.py`: added `get_subcommands_description()` to introspect `build_parser()` and generate usage and descriptions for all subcommands.
  - `scripts/test_orchestration_runs.py`: added `test_describe_run_subcommands_match_parser()` asserting every `run` subcommand of the argument parser appears in `ai-orch describe` output.
  - `tasks/micro/notes/T087-final-report.md`: this final report.
- **Verification:**
  - Every `run` subcommand of the argument parser appears in `ai-orch describe` output: done, `uvx --quiet pytest -q -p no:cacheprovider scripts/test_orchestration_runs.py -k test_describe_run_subcommands_match_parser` passed (1 passed, 122 deselected in 0.60s).
  - `./bin/ai-orch describe` shows them: done, verified via `./bin/ai-orch describe | jq .commands.run` showing all 13 subcommands (`kilo-agent`, `options`, `preview`, `start`, `mark-delivered`, `apply-verdict`, `accept-triage`, `cleanup`, `logs`, `cancel`, `_supervise`, `list`, `show`) with formatted usage and description.
- **Full suite:**
  - `uvx --quiet pytest -q -p no:cacheprovider ./scripts ./plugins`: 4 failed, 636 passed in 417.74s (0:06:57). The 4 failures (`scripts/test_orchestration_env.py::test_duplicate_name_reserialized_frontmatter_resolves_to_trash`, `scripts/test_orchestration_env.py::test_duplicate_name_folded_description_and_whitespace_resolves_to_trash`, `scripts/test_orchestration_invoke.py::test_get_process_descendants_and_kill`, and `scripts/test_orchestration_orchestrator.py::test_bounds_kill_runaway_stub`) are pre-existing and unrelated to our diff. All 123 tests in `scripts/test_orchestration_runs.py` passed.
- **Deviations from the task text:** none.
- **Open issues:** none.
