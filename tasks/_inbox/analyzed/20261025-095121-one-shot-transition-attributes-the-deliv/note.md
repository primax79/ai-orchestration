# N057 One-shot transition attributes the delivery step to the verifier

- id: N057
- title: One-shot transition attributes the delivery step to the verifier
- kind: bug
- status: processed
- created: 2026-10-25T09:51:21.459720+00:00
- author: ai-coding-tools
- about: tasks_engine.py transition walk (T035)
- produced: T057
- processed-by: ai-coding-tools

Closing T056 with 'tasks transition T056 done --verifier ai-coding-tools-c1 --reason R' (executor: kilo) wrote three Log lines all attributed to ai-coding-tools-c1, including 'in progress -> delivered'. The delivery was the executor's (kilo); the verifier only verified. A log that shows one session delivering and verifying weakens the independence record the guard protects. Expected: steps up to delivered attributed to the task's executor (or marked 'recorded by <actor> on behalf of <executor>'), only verified/done attributed to the verifier; the reason text repeated only where it applies.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (63cbdfd)
- Date: 2026-10-25 09:51:21 UTC
