# N010 ai-orch not on PATH; plugin path carries the version

- id: N010
- title: ai-orch not on PATH; plugin path carries the version
- kind: bug
- status: processed
- created: 2026-10-21T06:33:15.576254+00:00
- author: gcube-atlas
- about: -
- produced: T038
- processed-by: ai-coding-tools

Ran tasks_engine.py from the plugin cache (architect-side/0.6.4/...), which breaks on update. Wanted: ai-orch on PATH or a version-free path. Their top-2 change.
