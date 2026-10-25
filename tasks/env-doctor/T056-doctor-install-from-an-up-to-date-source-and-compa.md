# T056 Doctor: install from an up-to-date source and compare skill content, not the stored hash

- id: T056
- title: Doctor: install from an up-to-date source and compare skill content, not the stored hash
- category: env-doctor
- priority: P1
- priority-reason: Kilo kept outdated orchestration skills after a release; the Doctor called them up to date
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N056 (ai-coding-tools, releasing architect-side 0.7.0)
- paths: scripts/orchestration_env.py
- handoff: Read tasks/env-doctor/T056-doctor-install-from-an-up-to-date-source-and-compa.md, do the open steps, run the Verification, update the task and the registry.
- short: Doctor fresh skill installs

## Goal

install-skills and the status report compare the installed skill content with the source content (not the source_hash stored in .ai-orch-source.json), so an outdated copy is shown as outdated and replaced without --overwrite; the Doctor reports when its source clone (~/.ai-orchestration/repos/<repo>) is behind its remote, or when a configured local checkout is newer, and offers fetch-repos (preview); tests cover both.

## Steps

- [x] Update `detect_skill_state` and `detect_agent_state` in `scripts/orchestration_env.py` to compare installed content hash against current source content hash (`hash_directory` / `sha256`) rather than trusting the install-time marker `source_hash`.
- [x] Classify clean copies matching previous source versions as `outdated`, distinguishing them from locally modified copies (`modified-or-outdated`).
- [x] Update `install_skills` so that `outdated` copies (source newer) plan `REPLACE` with reason `(source newer)` without requiring `--overwrite`, while locally modified copies still require `--overwrite`.
- [x] Ensure receipt marker `.ai-orch-source.json` is updated with the current `source_hash` on replacement/installation.
- [x] Implement source clone staleness detection in `scripts/orchestration_env.py` (`check_source_repo_stale`, `check_source_repo_behind_remote`, `check_local_checkout_ahead`): report warnings in `env status` and `install-skills` when `~/.ai-orchestration/repos/<repo>` is behind its remote or when a configured local checkout is ahead, offering `ai-orch env fetch-repos --repos <repo>`.
- [x] Add unit tests in `scripts/test_orchestration_env.py` covering outdated copy replacement without `--overwrite`, local edit retention requiring `--overwrite`, marker updates on install, bare remote behind warning, offline tolerance, and local checkout ahead warning.

## Verification

- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/architect-side/skills/task-pipeline/scripts/ plugins/shared/skills/orchestration-setup/scripts/`: 563 passed in 381.60s.
- `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/test_orchestration_env.py`: 81 passed in 108.96s.
- Isolated live check in scratch temp directory: verified `install-skills` installs v1, source edit in scratch clone updates to v2, and subsequent dry-run plans `REPLACE` with `(source newer)` without `--overwrite`.
