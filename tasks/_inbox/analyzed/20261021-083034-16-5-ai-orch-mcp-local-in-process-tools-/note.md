# N042 16.5: ai-orch mcp --local (in-process tools) missing

- id: N042
- title: 16.5: ai-orch mcp --local (in-process tools) missing
- kind: bug
- status: processed
- created: 2026-10-21T08:30:34.563384+00:00
- author: d4science-python-library
- about: -
- produced: T045
- processed-by: ai-coding-tools

Validation of 16.5 (Broker MCP tools): its Goal promises 'ai-orch mcp --local' serving the tools in-process; 'bin/ai-orch mcp --help' answers 'Unknown command group: mcp' and no --local exists (only ai-orch-broker shim). 16.6 adds 'ai-orch mcp' (the shim) but not --local. The rest of 16.5 works (18 tools, paging, previews, stale expect_hash refused, error codes).
