# N058 reopen can target delivered when a task was closed by the wrong verifier

- id: N058
- title: reopen can target delivered when a task was closed by the wrong verifier
- kind: feature
- status: processed
- created: 2026-10-25T11:56:56.161538+00:00
- author: ai-coding-tools-c1
- about: -
- produced: T063
- processed-by: ai-coding-tools-c1

Closing a task with the wrong verifier (e.g. architect instead of the requester) needs reopen (-> open) then in-progress then delivered, and verify-by plus the pending line by hand. Proposal: 'reopen <id> --to delivered --verify-by <ws>' clears verifier, sets verify-by and writes the pending line, one Log line.

---
- Author: ai-coding-tools-c1
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (8e38c66)
- Date: 2026-10-25 11:56:56 UTC
