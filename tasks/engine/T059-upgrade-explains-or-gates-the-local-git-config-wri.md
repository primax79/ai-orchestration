# T059 upgrade explains or gates the local git config write of the index merge driver

- id: T059
- title: upgrade explains or gates the local git config write of the index merge driver
- category: engine
- priority: P3
- priority-reason: Declared in the plan already; requester note, not a blocker
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: porting-liferay-8c, T050 re-check 2026-10-25, note (a)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T059-upgrade-explains-or-gates-the-local-git-config-wri.md, do the open steps, run the Verification, update the task and the registry.
- short: Merge driver opt-in

## Goal

upgrade writes merge.ai-orch-index.driver into the target repo's .git/config with an absolute path into the user's home. Make it explicit: either an opt-in flag (e.g. --register-merge-driver, default on only when the launcher is on PATH) or a preview line saying what is written, that it is local to this clone, and what happens on a machine without ai-orch (git falls back to the normal text merge). Coordinate with T058 (dangling driver path).

## Steps

- [ ] Choose opt-in vs explanation (minor decision, architect)
- [ ] Implement and test

## Verification

- Preview shows the explanation line or the flag gates the write; tests cover both
