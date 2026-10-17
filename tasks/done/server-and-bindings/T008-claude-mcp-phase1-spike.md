# T008 `claude-mcp` Phase 1 empirical spike (Option A `--bg` vs Option B detached `-p`)

- id: T008
- title: claude-mcp Phase 1 empirical spike (Option A --bg vs Option B detached -p)
- category: server-and-bindings
- priority: P1
- priority-reason: Unblocks implementation of claude-mcp as second Executor binding (SPEC.md and 01-claude-mcp-server/plan.md ready)
- next-up: no
- state: done
- executor: claude
- depends-on: -
- decider: -
- sources: ../claude-mcp/SPEC.md (§3, §5), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../claude-mcp/
- handoff: Read tasks/server-and-bindings/T008-claude-mcp-phase1-spike.md and ../claude-mcp/SPEC.md, run the Phase 1 spike, record findings, and update the task and the registry.
- verifier: orchestrator:deep-reasoning

## Goal

Run the Phase 1 empirical spike defined in `../claude-mcp/SPEC.md` §5 to compare Option A (`claude "<task>" --bg --session-id <uuid>`) against Option B (detached `claude -p "<task>" --output-format json --session-id <uuid>`) on real CLI behavior, PID/cancellation control, and transcript JSONL tail-reading.

## Steps

1. In a scratch directory, test Option A and Option B with `claude` CLI on this machine.
2. Record exact JSON outputs, transcript path/shape under `~/.claude/projects/`, and cancellation behavior in `../claude-mcp/`.
3. Lock the chosen dispatch architecture in `../claude-mcp/SPEC.md` so Phase 2 (minimal MCP server) can proceed.

## Verification

- Spike report written in `../claude-mcp/` with real command outputs and architecture decision locked in `../claude-mcp/SPEC.md`.
