# T028 Unattended turns: enforce reduced capability on every tool and harden the untrusted-data delimiters

- id: T028
- title: Unattended turns: enforce reduced capability on every tool and harden the untrusted-data delimiters
- category: server-and-bindings
- priority: P1
- priority-reason: Gemini review 2026-10-18: Kilo event turns run with full tools; untrusted data can close its own delimiter
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/server-and-bindings/T028-unattended-turns-enforce-reduced-capability-on-eve.md, do the open steps, run the Verification, update the task and the registry.
- short: Unattended turn hardening

## Goal

Reduced-capability (triage/event_batch) turns are enforced only by Claude's allow-list and Codex's read-only sandbox; the Kilo adapter passes no restriction (orchestration_runs.py:2098-2116), so unattended Kilo turns can edit and run anything. And format_untrusted_event_data wraps data in fixed tags that the data itself can close. Enforce a restricted profile for Kilo unattended turns (verify Kilo's real permission/agent options in references/ or kilo --help before choosing; refuse to run an unattended Kilo turn if no restriction is available), and wrap untrusted data with a per-turn random nonce tag plus escaping, with tests.

## Steps

- [x] Implement task steps.

## Verification

- [x] Verify task implementation.
