# N060 transition to delivered accepts template placeholder Steps and Verification

- id: N060
- title: transition to delivered accepts template placeholder Steps and Verification
- kind: bug
- status: processed
- created: 2026-10-25T14:52:47.514820+00:00
- author: ai-coding-tools-c1
- about: -
- produced: T062
- processed-by: ai-coding-tools-c1

On 2026-10-25 T032-T034 (ai-coding-tools workspace) moved to delivered with '- [ ] Step 1' and '- Command or check that proves completion' still in place; only a later 'tasks validate' flagged it (found by ai-coding-tools-2c). Expected: 'transition <id> delivered' (and the done walk) refuses while either section is still the template placeholder, naming the section, like validate does.

---
- Author: ai-coding-tools-c1
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (fe9d033)
- Date: 2026-10-25 14:52:47 UTC
