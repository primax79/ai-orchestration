# T031 Conditional done: question age in the index; conditions: header position

- id: T031
- title: Conditional done: question age in the index; conditions: header position
- category: server-and-bindings
- priority: P3
- priority-reason: Follow-up of T030 reported by the Evolution Assurance central session (docs/08 §7.15)
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: -
- handoff: Read tasks/server-and-bindings/T031-conditional-done-question-age-in-the-index-conditi.md, do the open steps, run the Verification, update the task and the registry.
- short: Conditional done follow-ups

verification pending: run Verification checks (independent verifier)

## Goal

(1) The Conditional section of 00-INDEX.md shows, per task, each condition question with its age in days and its decider (e.g. 'Q003 (9 d, owner)'); conditions older than 7 days are listed in a short 'stale conditions' line with their decider; the same data is in the JSON (conditions: [{id, status, age_days, decider}]). (2) A header with conditions: in a non-canonical position is rejected without saying why: either accept optional fields in any position, or make the ordering error name the expected order (what the engine does for other optional fields must stay consistent).

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
