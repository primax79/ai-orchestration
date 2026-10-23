# T016 Study: are the Doctor's persistent findings real, and do we handle them right?

- id: T016
- title: Study: are the Doctor's persistent findings real, and do we handle them right?
- category: env-doctor
- priority: P1
- priority-reason: The owner sees many Doctor findings that never resolve; either they are false positives or the resolution path is broken, and both erode trust in the tool
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: claude
- depends-on: -
- decider: -
- sources: owner request (2026-10-17): "a lot of findings that do not resolve; check whether they are false alarms or whether we must change how we handle them"
- paths: scripts/orchestration_env.py, ../ai-orchestration-ui/frontend/src/components/EnvironmentDoctor.tsx
- handoff: Read tasks/env-doctor/T016-doctor-findings-study.md and produce the report in tasks/env-doctor/notes/.
- verifier: owner
- short: Doctor findings study

## Goal

For every finding the Doctor reports on this machine, establish:

1. whether it is **true** (a real duplicate, conflict or drift), **false** (a misclassification by the Doctor), or **true but not actionable by the Doctor** (for example a plugin copy that only the owner can disable);
2. what the resolution path is, and why it does not clear the finding today;
3. what must change: the classification rules, the resolution logic, the UI presentation (severity, grouping, "acknowledge/ignore"), or nothing.

## Steps

1. Run `env status --json` and every `--dry-run` plan (`resolve-conflicts`, `install-skills`, `register-mcp`) against the real home, read-only.
2. Inventory every finding by kind (`foreign`, `modified-or-outdated`, `unmanaged`, duplicate-name, trigger-conflict, stray config, MCP provenance and overrides), with counts.
3. For a sample of each kind, inspect the real files (content diff against the source repo or plugin copy, receipts, symlinks) and classify the finding as true, false or not actionable.
4. Trace in `orchestration_env.py` why the finding persists after the UI's resolution.
5. Write the report with proposed changes, each one sized and ready to become a task.

## Verification

- `tasks/env-doctor/notes/T016-report.md` exists, with evidence (commands, outputs, file:line) for every claim.
- The home was not modified: a find of files newer than a marker set at start returns nothing under `~/.claude`, `~/.kilo`, `~/.codex` and `~/.config/kilo`.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
