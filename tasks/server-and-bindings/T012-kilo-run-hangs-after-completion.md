# T012 kilo-mcp: detect `kilo run` processes that hang after finishing

- id: T012
- title: kilo-mcp: detect kilo run processes that hang after finishing
- category: server-and-bindings
- priority: P2
- priority-reason: Hung tasks report "running" for hours, hide completed work and keep processes alive; the orchestrator only noticed from log mtimes
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: session 2026-10-17: tasks b7d26daa26b6, c7b5f7011bdf, b3cccdf3051e, ae7733625e86 committed and wrote their Final Report around 00:33–00:47, but their `kilo run` processes stayed alive and idle until cancelled at 10:10
- paths: ../kilo-mcp/server.py
- handoff: Read tasks/server-and-bindings/T012-kilo-run-hangs-after-completion.md, do the open steps, run the Verification, update the task and the registry.

## Goal

When `kilo run` has finished its work (its JSON event stream emitted the session's final message / idle event) but the process does not exit, kilo-mcp notices, records the outcome, and terminates the process. `kilo_task_progress`/`kilo_task_status` must not report such a task as running.

## Steps

1. Reproduce: find what `kilo run --format json` emits at the end of a session (inspect a log of a hung task under `~/.local/share/kilo-mcp/tasks/`), and whether the hang correlates with something specific (an MCP child that never exits, a background shell).
2. In the task watcher: after a terminal event (or after the Final Report is parsed) plus a grace period (e.g. 60 s) with no new output, mark the task completed and terminate the process group.
3. `kilo_task_progress` reports `finished, process lingering` instead of "no session found" while in the grace period.

## Verification

- A unit test with a stub `kilo` that prints a final event and then sleeps forever: the task becomes `completed` within the grace period, and the stub is killed.
- A live run of a trivial task exits or is reaped within the grace period.
