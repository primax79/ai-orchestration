# N061 questions ask --from-task ignores --question, --context, --option, --recommended and --asked-by

- id: N061
- title: questions ask --from-task ignores --question, --context, --option, --recommended and --asked-by
- kind: bug
- status: processed
- created: 2026-10-25T14:53:57.753132+00:00
- author: ai-coding-tools
- about: -
- produced: T061
- processed-by: ai-coding-tools-c1

Repro (2026-10-25, workspace ai-coding-tools): `ai-orch tasks questions ask --tasks-dir tasks --from-task T009 --decider owner --asked-by ai-coding-tools --question '...?' --context '...' --option 'A=...' --option 'B=...' --recommended A --blocks T009`. Result Q001: question and title copied from the legacy decider text, context 'Converted from the legacy decider header ...; context to be completed by the owner', empty Options, recommended '-', asked-by 'owner', open-answer yes. Expected: explicit arguments win over the values derived from the task; derive only what is missing. I rewrote Q001 and Q002 by hand.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (40520bb)
- Date: 2026-10-25 14:53:57 UTC
