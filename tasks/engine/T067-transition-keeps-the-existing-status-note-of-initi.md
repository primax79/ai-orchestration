# T067 transition keeps the existing Status note of initiative tasks

- id: T067
- title: transition keeps the existing Status note of initiative tasks
- category: engine
- priority: P2
- priority-reason: Closing 148 ai-swissknife tasks erased the merge sha (the evidence) from every plan block
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-105658-transition-to-done-replaces-the-status-n/note.md
- paths: -
- handoff: Read tasks/engine/T067-transition-keeps-the-existing-status-note-of-initi.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: ai-coding-tools
- short: Keep status evidence

## Goal

In ai-swissknife (2026-10-27) the initiative task blocks had '- **Status:** `delivered` (merged <sha> <date>)'. 'tasks transition <id> done --verifier X' rewrote the note to '(2026-10-27; X)', so the merge sha (the evidence) vanished from plan.md; I recovered it from git history for the summaries. Expected: keep the existing note and append the closure ('merged <sha> <date>; done 2026-10-27, verifier X'), or move the old note into a Log line.

## Steps

- [ ] transition on an initiative task block keeps the existing note and appends the new event ('merged <sha> <date>; done 2026-10-27, verifier X'), or moves the old note into the block's log

## Verification

- Test: block with '(merged abc123 2026-10-08)' transitioned to done keeps abc123 in plan.md
