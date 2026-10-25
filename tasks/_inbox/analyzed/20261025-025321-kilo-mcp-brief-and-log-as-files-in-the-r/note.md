# N053 kilo-mcp: brief and log as files in the repo

- id: N053
- title: kilo-mcp: brief and log as files in the repo
- kind: feature
- status: processed
- created: 2026-10-25T02:53:21.235105+00:00
- author: gcube_audit
- about: kilo-mcp/server.py
- produced: ai-coding-tools:T033
- processed-by: ai-coding-tools

gcube_audit keeps each Kilo brief as a versioned file in the repo (services/kilo-tasks/<name>.md) with its log next to it (services/logs/), so another session or model can resume or re-check a run without the MCP history. kilo-mcp writes the spec to a temp file it deletes and the log under ~/.local/share/kilo-mcp/tasks. Wanted: kilo_implement(brief_file=<repo path>) that uses the file as the spec as-is (plus the contract sections), and log_dir=<repo path> to write the run log there (also kept in the usual place).
