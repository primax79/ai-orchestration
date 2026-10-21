# N033 kilo_implement continue_session_id on a running session starts a second process

- id: N033
- title: kilo_implement continue_session_id on a running session starts a second process
- kind: bug
- status: processed
- created: 2026-10-21T07:26:29.171439+00:00
- author: gcube_audit
- about: -
- produced: ai-coding-tools:T020
- processed-by: ai-coding-tools

Calling kilo_implement with continue_session_id while the first run of that session is still active (same worktree) starts a second detached kilo process instead of queueing the message; the tool only prints a collision warning. Expected (per the tool description 'queues a follow-up message even into a still-running session'): queue into the running process, or refuse with an error. Worked around by cancelling both runs and relaunching once.
