# Final Report: T089 test isolation and session guard

- **Outcome:** delivered.
- **Files changed:**
  - `conftest.py`: added function-scoped autouse fixture `_isolate_test_environment` isolating `HOME`, `AI_ORCHESTRATION_CONFIG`, `AI_ORCH_CONFIG_DIR`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `KILO_MCP_DATA_DIR` under `tmp_path / "_isolated_home"` for every test; added session guard `_session_guard_unpolluted_host` taking pre/post-session recursive snapshots of the real host `~/.config/ai-orchestration` and `~/works` (excluding the repository family `~/works/ai-coding-tools` where this worktree and parallel executors live) asserting zero files are created, modified, or deleted during the test run.
  - `scripts/test_orchestration_orchestrator.py`: updated `test_reassign_dry_run_diff_header_home_relative` to set `HOME` and clear `AI_ORCH_CONFIG_DIR` alongside `AI_ORCHESTRATION_CONFIG` so its diff relative-path logic matches the isolated test home.
  - `scripts/test_test_isolation.py`: added dedicated unit tests for test isolation (env vars, `Path.home()` fallback, subprocess inheritance, and session guard mutation detection).
  - `tasks/micro/notes/T089-final-report.md`: this final report.
- **Verification:**
  - Autouse fixture in root `conftest.py` isolating `HOME`, `AI_ORCHESTRATION_CONFIG`, `AI_ORCH_CONFIG_DIR`, `XDG_CONFIG_HOME`, and `KILO_MCP_DATA_DIR` under `tmp_path` for every test: done, `uvx --quiet pytest -q -p no:cacheprovider scripts/test_test_isolation.py` passed (4 passed in 5.60s).
  - Session guard proving nothing under the real `~/.config/ai-orchestration` or `~/works` is created/modified: done, verified via `_session_guard_unpolluted_host` across the full test suite with 0 violations.
  - Find and fix the test that created `~/.config/ai-orchestration/projects/p/orchestration.toml` with title "p": done. Root cause identified: during task 19.2/19.3 verification at `2026-10-30 01:25:09`, `create_updated_project_fixture` / `plan_workspace_register` was invoked on temporary path `/tmp/tmpogvuxcag/p` (matching UUID `c777f761-7b3a-4eff-8576-2410d54119c2` in registry sqlite and title "p"). Prior to commit `838825d`, `plan_workspace_register` called `find_project_config_path(canonical, for_write=True)` without forwarding `config_dir`, and `HOME` was not isolated, causing the fallback to write directly to `~/.config/ai-orchestration/projects/p/orchestration.toml`. The code path is now guarded both in `plan_workspace_register` (`_gpath` forwarding) and by isolating `HOME`, `AI_ORCHESTRATION_CONFIG`, and `AI_ORCH_CONFIG_DIR` in `conftest.py` so any registration or upgrade strictly targets the per-test isolated directory.
- **Full suite:**
  - `uvx --quiet pytest -q -p no:cacheprovider ./scripts ./plugins`: 693 passed in 403.69s (0:06:43).
- **Deviations from the task text:** none.
- **Open issues:** none.
