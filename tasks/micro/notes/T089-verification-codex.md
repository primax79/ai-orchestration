# T089 verification (Codex, 2026-10-30): BOUNCE

Verified on `integration/19` (executor commit bdab4e8). No test was skipped or weakened, and subprocesses inherit the isolated environment when the root fixture is loaded.

- **B1 (high)**: `conftest.py:87`. When pytest is launched from a nested directory (`plugins/*/skills/*/scripts`), that directory becomes the rootdir and the root `conftest.py` is never loaded. Fix: add a `pytest.ini` (or `pyproject.toml`) at the repository root that anchors the rootdir, and verify an invocation from a nested directory.
- **B2 (high)**: `conftest.py:20-21,55,58`. The guard excludes all of `~/works/ai-coding-tools`, so it proves nothing. At the same time, checking the whole of `~/works` would turn concurrent writes by other projects into false failures.
  - **Required (orchestrator):** guard everything under the real `~/.config/ai-orchestration`. Under `~/works`, guard ONLY the orchestration config files of each project: `.ai-orchestration.local.toml`, `orchestration.toml`, `tasks/orchestration.toml`, `.ai-orchestration.toml` and the `.ai-orchestration/` directory. Exclude only the repository under test, resolved from the rootdir, and its worktrees. Never exclude the whole parent workspace.
- **B3 (medium)**: the report does not name the test that created project `p`, and no test in the repository uses that name. Identify the exact test, or say that it was an ad-hoc invocation by an executor or verifier, and add a regression test that reproduces the write and proves it stays contained.

## Round 2 (Codex, 2026-10-30, fix commit 9f99100): BOUNCE on B2, accepted by the orchestrator with a caveat

- **B1 is fixed:** the root `pytest.ini` anchors the rootdir, test collection is unchanged (698 → 701, the 3 new tests), and the fixtures load from a nested directory.
- **B3 is fixed:** project `p` came from an ad-hoc executor smoke invocation, and a containment regression test was added.
- **B2:** the guard is read-only and tolerates unrelated concurrent activity. But it skips directories named `repos`, `build`, `dist`, `target`, etc. and almost all hidden directories (`conftest.py:30-47,183-188`), so it does not guard configs below them (for example `~/works/gcube_repos/repos/...`).
- **Orchestrator decision (2026-10-30):** accepted as a performance trade-off. `~/works/gcube_repos` holds about 640 read-only clones, and scanning them on every test session is not justified. **Caveat:** the guard does not cover projects inside directories with those names. A follow-up can turn the generic name list into an explicit, configurable exclusion list if a leak ever shows up there.
