# server-and-bindings

owner-session: unassigned

## Goal and scope

Server-side evolutions in `../kilo-mcp/server.py` (blocking completion wait `kilo_task_wait`, decision telemetry `kilo_log_decision`, structured verification gate) and new Executor bindings (`../claude-mcp/` Phase 1 spike and server, Pi evaluation). State and priority of its tasks are in `tasks/00-INDEX.md`; working notes are in `notes/` next to this file.

## Start a session on the whole category

> Read tasks/server-and-bindings/README.md and its tasks in priority order, set owner-session, work the tasks one at a time (P0 first), and keep the task files, this README and tasks/00-INDEX.md current.

## Rules

- Only the owner session edits the task files and this README; others add notes below or create new T### tasks.
- A finished task moves with `git mv` to `tasks/done/server-and-bindings/`, same name.

## Shared notes
