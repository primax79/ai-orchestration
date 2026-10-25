# N051 questions move accepts an already answered question without warning

- id: N051
- title: questions move accepts an already answered question without warning
- kind: bug
- status: processed
- created: 2026-10-25T02:51:25.432719+00:00
- author: gcube_audit
- about: -
- produced: T052
- processed-by: ai-coding-tools

T041 validation (OK overall): 'questions move Q### --to <url>' also accepted a question already 'answered', silently. Expected: refuse, or warn and require --force, since an answered question has a decision that should be applied, not moved.
