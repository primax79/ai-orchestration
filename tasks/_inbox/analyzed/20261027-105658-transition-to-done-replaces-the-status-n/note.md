# N065 transition to done replaces the Status note of an initiative task and drops its evidence

- id: N065
- title: transition to done replaces the Status note of an initiative task and drops its evidence
- kind: bug
- status: processed
- created: 2026-10-27T10:56:58.836447+00:00
- author: ai-coding-tools-c1
- about: -
- produced: T067
- processed-by: ai-coding-tools-c1

In ai-swissknife (2026-10-27) the initiative task blocks had '- **Status:** `delivered` (merged <sha> <date>)'. 'tasks transition <id> done --verifier X' rewrote the note to '(2026-10-27; X)', so the merge sha (the evidence) vanished from plan.md; I recovered it from git history for the summaries. Expected: keep the existing note and append the closure ('merged <sha> <date>; done 2026-10-27, verifier X'), or move the old note into a Log line.

---
- Author: ai-coding-tools-c1
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (aed1caa)
- Date: 2026-10-27 10:56:58 UTC
