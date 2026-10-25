# N050 common-tools:gitignore drops project rules that follow the old gitignore.io block

- id: N050
- title: common-tools:gitignore drops project rules that follow the old gitignore.io block
- kind: bug
- status: ready
- created: 2026-10-23T21:30:26.619078+00:00
- author: gcube_audit
- about: -
- produced: -
- processed-by: -
- short: common-tools:gitignore drops project

Skill common-tools:gitignore (gcube-ai-toolkit). When a repository's .gitignore has project-specific rules placed AFTER an existing Toptal/gitignore.io generated block, the regeneration silently drops them instead of keeping them at the head. Seen on two gCube Maven repositories (2026-10-23): patterns excluding sensitive test resources were lost. Expected: every non-template line of the original file preserved (moved to the custom head), and a diff/report of what was moved. Actual: lines after the block removed without warning. Workaround in use: diff base vs new .gitignore and restore by hand.

---
- Author: gcube_audit
- Workspace: /Users/Alfredo/works/gcube_audit
- ai-orch: 1.1.0 (c7e9c57)
- Date: 2026-10-23 21:30:26 UTC
