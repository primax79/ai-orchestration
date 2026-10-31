# Final Report — T090 (`tasks upgrade: proteggere le modifiche dell'utente nel blocco gestito di tasks/AGENTS.md`)

- **Outcome:** delivered
- **Files changed:**
  - `plugins/shared/skills/orchestration-setup/scripts/orchestration_config.py`
  - `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py`
  - `plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py`
  - `scripts/orchestration_env.py`
  - `scripts/test_orchestration_env.py`
  - `tasks/micro/notes/T090-final-report.md`
- **Verification:**
  - `replace the managed block only if its content matches the current rendering or a historical one, exactly after whitespace normalization`: done — `uvx --quiet --python 3.12 pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py scripts/test_orchestration_env.py -k "t090 or t050_agents_md"` (4 passed, 0 failed; reuses `orchestration_config._managed_block_matches_known_rendering` with the current rendering and all historical `CANONICAL_TASKS_AGENTS_MD` renderings across git history).
  - `otherwise keep it, report it for manual review, and do not apply the upgrade to that block`: done — `uvx --quiet --python 3.12 pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py scripts/test_orchestration_env.py -k "t090"` (3 passed, 0 failed; `render_upgraded_agents_md` raises `TasksAgentsMdManagedBlockModifiedError`, and `upgrade_tasks_tree`, `upgrade_project`, and `inspect_project_doctor` preserve `tasks/AGENTS.md` byte-for-byte, report `"tasks/AGENTS.md <!-- ai-orch:managed begin --> block"` in `manual_review_sections` and `warnings`, and skip upgrading that block while still applying other upgrade steps).
  - `Add a test with a user edit inside the block, and a test showing that an unmodified block is still updated normally`: done — `uvx --quiet --python 3.12 pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py scripts/test_orchestration_env.py -k "t090 or t050_agents_md"` (4 passed, 0 failed; `test_t090_tasks_agents_md_managed_block_protects_user_edits_and_updates_unmodified_historical` and `test_t090_standalone_without_orchestration_config_keeps_agents_md_and_upgrades_other_files` in `test_tasks_engine.py`, and `test_t090_upgrade_project_and_doctor_protect_user_edited_tasks_agents_md_block` in `test_orchestration_env.py`).
- **Full suite:** `uvx --quiet --python 3.12 pytest -q -p no:cacheprovider ./scripts ./plugins` — `759 passed, 1 failed in 433.40s (0:07:13)`. The 1 failure (`plugins/shared/skills/orchestration-setup/scripts/test_orchestration_config.py::test_19_18_macos_preflight_listen_backlog_and_port_checks`) is unrelated to this diff (belongs to task 19.18 preflight socket listen(1) backlog test on Linux).
- **Deviations from the task text:** None.
- **Open issues:** None.

## Bounce 1

- **B1 (high)** (`plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py:959-977`): fixed — removed the local fallback normalization/matching predicate in `_tasks_agents_managed_block_matches_known_rendering` and returned `False` whenever `orchestration_config` (or `_managed_block_matches_known_rendering`) cannot be imported, so `render_upgraded_agents_md` raises `TasksAgentsMdManagedBlockModifiedError` and `upgrade_tasks_tree` keeps `tasks/AGENTS.md` byte-for-byte and reports `"tasks/AGENTS.md <!-- ai-orch:managed begin --> block"` in `manual_review_sections` and `warnings` while still upgrading the other files.
- **Tests:** added `test_t090_standalone_without_orchestration_config_keeps_agents_md_and_upgrades_other_files` in `plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py` (loads an isolated copy of `tasks_engine.py` with `orchestration_config` blocked from import, and also tests with `monkeypatch.setattr(te, "orchestration_config", None)`).
- **Results:** `uvx --quiet --python 3.12 pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/test_tasks_engine.py scripts/test_orchestration_env.py -k "t090 or t050_agents_md"` → `4 passed in 4.20s`.

