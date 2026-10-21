# N041 transition --reason/--verifier not recorded in the task file

- id: N041
- title: transition --reason/--verifier not recorded in the task file
- kind: bug
- status: processed
- created: 2026-10-21T08:20:30.180273+00:00
- author: gcube_atlas
- about: -
- produced: T035
- processed-by: ai-coding-tools

Where: ai-orch tasks transition <id> verified --verifier owner --reason '...' then transition <id> done, on single-file emergent tasks in ~/works/gcube_atlas/tasks (T002-T004, 2026-10-21). Expected: the verifier and the reason (here the owner's approval) are written in the task, since the skill requires the approval to be recorded (PROGRESS.md or the task). Actual: the file only changes state and moves to done/; reason and verifier appear nowhere in it, so I appended a Closure section by hand. Suggest: append a dated line (state, actor, verifier, reason) to PROGRESS.md, or to a ## Log section for single-file tasks.

---
- Author: gcube_atlas
- Workspace: /Users/Alfredo/works/gcube_atlas
- ai-orch: 1.1.0 (02436a9)
- Date: 2026-10-21 08:20:30 UTC
