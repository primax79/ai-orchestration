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

- [ ] Step 1

## Verification

- Command or check that proves completion
