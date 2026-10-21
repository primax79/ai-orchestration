# N046 gcube_atlas handover: use the atlas inbox

- id: N046
- title: gcube_atlas handover: use the atlas inbox
- kind: note
- status: processed
- created: 2026-10-21T08:41:45.296789+00:00
- author: gcube_atlas
- about: -
- produced: T044
- processed-by: ai-coding-tools

From 2026-10-21 the gcube_atlas maintainer work moves from a Claude session to a Kilo/Gemini session that cannot receive cross-session messages. Send requests for gcube_atlas with: ~/works/ai-coding-tools/ai-orchestration/bin/ai-orch inbox add --tasks-dir ~/works/gcube_atlas/tasks --kind request --title ... --body ... --author <your workspace> --status ready. Feedback from the atlas keeps coming through ai-orch feedback. Open from us: N041.
