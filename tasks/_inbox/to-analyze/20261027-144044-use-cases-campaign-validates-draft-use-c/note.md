# N067 use-cases campaign validates draft use cases and marks them failing

- id: N067
- title: use-cases campaign validates draft use cases and marks them failing
- kind: bug
- status: ready
- created: 2026-10-27T14:40:44.934512+00:00
- author: ai-coding-tools
- about: -
- produced: -
- processed-by: -
- short: use-cases campaign validates draft

run_validation_campaign (tasks_engine.py ~7265) says 'Execute all active use cases' but iterates every discovered use case, drafts included; record_use_case_validation then sets status failing on a fail. In git-code-rag (2026-10-25 17:00 UTC) a campaign turned 10 post-v0 draft use cases (deliberately unimplemented, probe exits 1) into 'failing', and ran probes of v0 use cases before their tests existed: 39/41 failing, which the owner read as a broken product. Expected: the campaign skips status draft (or reports them as 'not in scope' without changing status), and reports UNTESTED rather than FAIL when the probe's files do not exist yet would also help. Also consider not running a campaign automatically while linked tasks are still open.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (d6520d1)
- Date: 2026-10-27 14:40:44 UTC
