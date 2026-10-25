# N059 sync-index never adds rows for new initiatives

- id: N059
- title: sync-index never adds rows for new initiatives
- kind: bug
- status: processed
- created: 2026-10-25T13:02:16.338658+00:00
- author: dave_agent
- about: -
- produced: T060
- processed-by: ai-coding-tools-c1

In dave_agent (2026-10-25) initiatives 40-45 existed as NN-slug/plan.md, were parsed by 'tasks list' and counted by 'tasks validate' (46 initiatives), but 'tasks sync-index --apply' never added them to the generated initiatives table in 00-INDEX.md: it only refreshed the status of rows already present (17, 20). After adding the six rows by hand inside the ai-orch:generated block, a re-sync kept them and filled in the derived status (e.g. 'in progress (done: 40.1-40.2, 40.11; next: 40.3-40.10)'). Expected: sync-index renders one row per parsed initiative, adding missing ones. Also: without --apply the command only previews, which is easy to miss ('[ok]' style output would help to say 'preview only, not written').

---
- Author: dave_agent
- Workspace: /Users/Alfredo/works/dave_agent
- ai-orch: 1.1.0 (ee1aba7)
- Date: 2026-10-25 13:02:16 UTC
