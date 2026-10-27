# N066 sync-index keeps stale initiative link labels after the plan title changes

- id: N066
- title: sync-index keeps stale initiative link labels after the plan title changes
- kind: bug
- status: ready
- created: 2026-10-27T12:21:38.734373+00:00
- author: ai-coding-tools-c1
- about: -
- produced: -
- processed-by: -
- short: Stale initiative labels

After translating plan titles (T036, 2026-10-27) sync-index reported 'already in sync' in ai-orchestration (15 rows) and ai-swissknife (50 rows) while the Initiatives/Done link labels still showed the old English titles; I rewrote them with a script. The T050 rule that keeps a hand-curated label treats any label shorter than the title as curated. Expected: a label equal to a PREVIOUS title of the plan is not curated and follows the current title, or a 'sync-index --refresh-labels' option.

---
- Author: ai-coding-tools-c1
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (45cad73)
- Date: 2026-10-27 12:21:37 UTC
