# T089 verification (Codex, 2026-10-30): BOUNCE

Verified on `integration/19` (executor commit bdab4e8). No test was skipped or weakened, and subprocesses inherit the isolated environment when the root fixture is loaded.

- **B1 (high)**: `conftest.py:87`. When pytest is launched from a nested directory (`plugins/*/skills/*/scripts`), that directory becomes the rootdir and the root `conftest.py` is never loaded. Fix: add a `pytest.ini` (or `pyproject.toml`) at the repository root that anchors the rootdir, and verify an invocation from a nested directory.
- **B2 (high)**: `conftest.py:20-21,55,58`. The guard excludes all of `~/works/ai-coding-tools`, so it proves nothing. At the same time, checking the whole of `~/works` would turn concurrent writes by other projects into false failures.
  - **Required (orchestrator):** guard everything under the real `~/.config/ai-orchestration`. Under `~/works`, guard ONLY the orchestration config files of each project: `.ai-orchestration.local.toml`, `orchestration.toml`, `tasks/orchestration.toml`, `.ai-orchestration.toml` and the `.ai-orchestration/` directory. Exclude only the repository under test, resolved from the rootdir, and its worktrees. Never exclude the whole parent workspace.
- **B3 (medium)**: the report does not name the test that created project `p`, and no test in the repository uses that name. Identify the exact test, or say that it was an ad-hoc invocation by an executor or verifier, and add a regression test that reproduces the write and proves it stays contained.
