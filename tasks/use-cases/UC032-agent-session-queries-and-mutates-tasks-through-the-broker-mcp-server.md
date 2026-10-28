# UC032 - Agent session queries and mutates tasks through the broker MCP server

- id: UC032
- title: Agent session queries and mutates tasks through the broker MCP server
- actor: Architect session
- approval: proposed
- priority: P1
- linked-tasks: 16.1, 16.2, 16.5, 16.6, T032, T045
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Use broker MCP tools

## Description & Business Value
Exposes workspace, project, task, question, and inbox operations over the MCP protocol (via the singleton broker or in-process ai-orch mcp --local stdio server) with compact null-free JSON responses, CAS hashes, and idempotency keys. Source: tasks/specs/orchestration-broker-mcp.md §3

## Preconditions
- Assistant is connected to ai-orch mcp (or ai-orch mcp --local).

## Scenario / Interaction Steps
1. The MCP client initializes the stdio session with ai-orch mcp.
2. The session calls broker tools (whoami, workspaces.list, tasks.list, tasks.new, tasks.transition) passing explicit workspace/project arguments and optional idempotency_key/expect_hash.
3. The server executes the operation under the shared on-disk lock and returns a compact null-free JSON payload.

## Automated Verification Command
```bash
T=$(mktemp -d) && printf "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1.0\"}}}\n{\"jsonrpc\":\"2.0\",\"method\":\"notifications/initialized\",\"params\":{}}\n{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"whoami\",\"arguments\":{}}}\n" | PATH="/opt/homebrew/bin:$PATH" AI_ORCHESTRATION_CONFIG="$T/cfg/orchestration.toml" ./bin/ai-orch mcp --local | tail -n 1 | jq -e ".result.content[0].text | fromjson | .ok == true" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] MCP tool schemas and JSON responses omit `null` fields so strict clients (Claude Code, Kilo, Codex) accept the server without dropping tools.
- [ ] Read list tools (`tasks.list`, `workspaces.list`, `questions.list`) are compact, paged (`cursor`/`next_cursor`), and capped at 256 KiB.
- [ ] Mutating MCP calls share the on-disk `tasks/.ai-orch.lock` with the CLI, verify `expect_hash`, and deduplicate retries via `idempotency_key`.

## AI Validation Log

