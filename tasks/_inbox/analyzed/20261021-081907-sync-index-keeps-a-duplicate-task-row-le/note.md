# N040 sync-index keeps a duplicate task row left by a merge

- id: N040
- title: sync-index keeps a duplicate task row left by a merge
- kind: bug
- status: processed
- created: 2026-10-21T08:19:07.641629+00:00
- author: gcube_audit
- about: -
- produced: T037
- processed-by: ai-coding-tools

After a git merge that left two identical rows for the same task in the tasks-by-category table of 00-INDEX.md, 'sync-index --apply' (vendored copy in the workspace) kept both rows instead of regenerating the table from headers. Expected: generated sections rebuilt from task headers, one row per id. Worked around with a manual dedupe.

---
- Author: gcube_audit
- Workspace: /Users/Alfredo/works/gcube_audit
- ai-orch: 1.1.0 (02436a9)
- Date: 2026-10-21 08:19:07 UTC
