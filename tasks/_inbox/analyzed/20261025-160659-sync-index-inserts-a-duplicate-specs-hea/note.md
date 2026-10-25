# N062 sync-index inserts a duplicate '## Specs' heading after an unmarked Initiatives table

- id: N062
- title: sync-index inserts a duplicate '## Specs' heading after an unmarked Initiatives table
- kind: bug
- status: ready
- created: 2026-10-25T16:06:59.808456+00:00
- author: ai-coding-tools
- about: -
- produced: -
- processed-by: -
- short: sync-index inserts duplicate Specs

Repro: git-code-rag/tasks/00-INDEX.md created by 'tasks upgrade', then hand-added unmarked '## Initiatives' and '## Specs' tables (as in the template.md skeleton). 'tasks sync-index --apply' renders '| L |\n## Specs\n\n## Specs' (heading glued to the Initiatives table plus a duplicate) and an extra blank line before '## Next up'. Removing the duplicate by hand makes '--check' fail again, so the clean form cannot be kept. Expected: unmarked Initiatives/Specs sections are left byte-identical (or wrapped in generated markers) and the render is a fixed point.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (6ae7c50)
- Date: 2026-10-25 16:06:59 UTC
