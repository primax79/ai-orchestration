# T062 transition to delivered refuses template placeholder sections

- id: T062
- title: transition to delivered refuses template placeholder sections
- category: engine
- priority: P2
- priority-reason: Tasks reach delivered with empty Steps/Verification; only validate catches it later
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261025-145247-transition-to-delivered-accepts-template/note.md
- paths: -
- handoff: Read tasks/engine/T062-transition-to-delivered-refuses-template-placehold.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: ai-coding-tools
- short: No delivery with placeholders

## Goal

On 2026-10-25 T032-T034 (ai-coding-tools workspace) moved to delivered with '- [ ] Step 1' and '- Command or check that proves completion' still in place; only a later 'tasks validate' flagged it (found by ai-coding-tools-2c). Expected: 'transition <id> delivered' (and the done walk) refuses while either section is still the template placeholder, naming the section, like validate does.

## Steps

- [ ] transition <id> delivered and the done walk refuse while Steps or Verification is still the template placeholder, naming the section

## Verification

- Test: placeholder Steps -> refused with the section named; filled -> accepted
