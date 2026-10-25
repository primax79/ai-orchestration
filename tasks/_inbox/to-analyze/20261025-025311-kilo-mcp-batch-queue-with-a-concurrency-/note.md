# N052 kilo-mcp: batch queue with a concurrency cap

- id: N052
- title: kilo-mcp: batch queue with a concurrency cap
- kind: feature
- status: ready
- created: 2026-10-25T02:53:11.421775+00:00
- author: gcube_audit
- about: kilo-mcp/server.py
- produced: -
- processed-by: -
- short: kilo batch queue

Why gcube_audit runs Kilo through its own wrapper (services/scripts/kilo_task.sh + a pgrep-based queue script, since 2026-10-14) instead of kilo-mcp: it launches batches of 40+ long read-only briefs and walks away, with at most N runs at once. kilo-mcp runs survive the session (detached) but have no queue: wanted a kilo_queue (or kilo_implement queue=true) that holds runs and starts them as slots free up, with a configurable cap, visible in kilo_task_status.
