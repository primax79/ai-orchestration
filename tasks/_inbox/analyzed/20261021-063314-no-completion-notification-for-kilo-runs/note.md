# N005 No completion notification for Kilo runs

- id: N005
- title: No completion notification for Kilo runs
- kind: feature
- status: processed
- created: 2026-10-21T06:33:14.117504+00:00
- author: gcube-audit
- about: -
- produced: ai-coding-tools:T018
- processed-by: ai-coding-tools

Coordinator keeps a shell waiter per run; kill -0 reported 'running' after the run ended (ps -p works). Wanted: completion notification, or kilo_task_wait that blocks without timing out on long runs. Part of their top-2 change.
