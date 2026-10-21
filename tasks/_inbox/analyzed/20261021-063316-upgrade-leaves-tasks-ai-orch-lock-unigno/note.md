# N012 upgrade leaves tasks/.ai-orch.lock unignored

- id: N012
- title: upgrade leaves tasks/.ai-orch.lock unignored
- kind: bug
- status: processed
- created: 2026-10-21T06:33:16.193234+00:00
- author: gcube-atlas
- about: -
- produced: T038
- processed-by: ai-coding-tools

upgrade creates tasks/.ai-orch.lock and only warns that git does not ignore it. Wanted: upgrade writes tasks/.gitignore with the lock, or keeps the lock outside the tree.
