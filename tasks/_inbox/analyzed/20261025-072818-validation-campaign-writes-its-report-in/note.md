# N055 validation campaign writes its report into tasks/reports, which then becomes a task category in 00-INDEX.md

- id: N055
- title: validation campaign writes its report into tasks/reports, which then becomes a task category in 00-INDEX.md
- kind: bug
- status: processed
- created: 2026-10-25T07:28:18.272542+00:00
- author: ai-coding-tools
- about: -
- produced: T055
- processed-by: ai-coding-tools

Where: tasks_engine.py ~6755 (reports_dir = tasks_dir / 'reports'). On 2026-10-18 a campaign run wrote tasks/reports/validation-campaign-1792277410.md (0/0 use cases) into the ai-coding-tools workspace tree. sync-index then listed 'reports' as a category with a link to a missing reports/README.md. After deleting the directory the section stayed, because sync-index keeps categories already present in the index (existing_by_cat); I removed it by hand (commit 7284c48). Expected: campaign reports go outside the category namespace (e.g. tasks/_reviews/ or a configurable path), and sync-index drops a category section whose directory no longer exists and whose table is empty.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (cfadf05)
- Date: 2026-10-25 07:28:18 UTC
