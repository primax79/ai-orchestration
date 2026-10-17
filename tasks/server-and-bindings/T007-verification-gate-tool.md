# T007 Structured verification gate tool in `kilo-mcp`

- id: T007
- title: Structured verification gate tool in kilo-mcp
- category: server-and-bindings
- priority: P2
- priority-reason: Reduces Phase 5 Architect context consumption by returning structured pass/fail check verdicts instead of full log dumps
- next-up: yes
- state: in progress
- executor: kilo
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§3.2), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../kilo-mcp/server.py, ../kilo-mcp/test_server.py
- handoff: Read tasks/server-and-bindings/T007-verification-gate-tool.md, do the open steps, run the Verification, update the task and the registry.

## Goal

Add a verification gate capability to `kilo-mcp/server.py` that runs project check commands (lint, test, build) in a target `working_directory`/worktree and returns a compact structured verdict (pass/fail per command + failing output tail only).

## Steps

1. Design whether this is a dedicated `@mcp.tool() kilo_verify_worktree` or a structured check mode, supporting explicit commands or TOML-configured project checks.
2. Implement in `../kilo-mcp/server.py` with timeout protection and output truncation on passing checks.
3. Add unit tests in `../kilo-mcp/test_server.py` and document in `../kilo-mcp/README.md`.

## Verification

- `../kilo-mcp/.venv/bin/pytest ../kilo-mcp/test_server.py` passes.
