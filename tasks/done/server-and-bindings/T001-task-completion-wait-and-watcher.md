# T001 Task completion wait (`kilo_task_wait`) and watcher guidance

- id: T001
- title: Task completion wait (kilo_task_wait) and watcher guidance
- category: server-and-bindings
- priority: P1
- priority-reason: Eliminates wasted polling turns and unreported completed tasks in background delegations
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../task-completion-notification-spec.md, docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../kilo-mcp/server.py, ../kilo-mcp/test_server.py, ../kilo-mcp/bindings/orchestration-methodology.json, ../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md
- handoff: Read tasks/server-and-bindings/T001-task-completion-wait-and-watcher.md, do the open steps, run the Verification, update the task and the registry.
- verifier: orchestrator:deep-reasoning
- short: Task wait guidance

## Goal

Add `kilo_task_wait(task_id, timeout_seconds=None)` to `kilo-mcp/server.py` (with full crash/log-file reconciliation via `_reconcile_task_if_orphaned`) and update the orchestration skills (`orchestration-methodology` + `kilo-mcp-orchestrator`) so background tasks are awaited deterministically (with the shell PID watcher documented as fallback for clients without blocking wait support).

## Steps

1. In `../kilo-mcp/server.py`, implement `@mcp.tool() async def kilo_task_wait(task_id: str, timeout_seconds: int | None = None) -> str` that waits until the task reaches a terminal state (reconciling orphaned PIDs from log files on each check), returning the same payload as `kilo_task_result` or a clear "still running" status on timeout without raising.
2. Add unit tests in `../kilo-mcp/test_server.py` covering normal completion, timeout, and a task whose launching process died mid-run (log-file recovery).
3. Update `../ai-architect-executor/plugins/architect-side/skills/orchestration-methodology/SKILL.template.md` and `../kilo-mcp/bindings/orchestration-methodology.json` Phase 4 to instruct awaiting completion via `kilo_task_wait` (or the background PID watcher fallback `while kill -0 <pid> 2>/dev/null; do sleep 10; done`) instead of timer polling.
4. Regenerate generic and bound skills and update `../kilo-mcp/README.md`, `ARCHITECTURE.md`, and `SPEC_MCP_ORCHESTRATION.md`.

## Verification

- `../kilo-mcp/.venv/bin/pytest ../kilo-mcp/test_server.py` passes including the new `kilo_task_wait` tests.
- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` exits 0.
