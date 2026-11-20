# N100 kilo_implement ignores working_directory and runs in the MCP server cwd

- id: N100
- title: kilo_implement ignores working_directory and runs in the MCP server cwd
- kind: bug
- status: ready
- created: 2026-11-20T19:05:04.802230+00:00
- author: aai-workgroup
- about: kilo-mcp kilo_implement
- produced: -
- processed-by: -
- short: kilo_implement ignores working_directory

Observed 2026-11-20 (AAI Workgroup session), twice. kilo_implement called with working_directory=/Users/Alfredo/works/dev/review-T026 (a git repo) and brief_file in that directory; Kilo ran in the MCP server's cwd (/Users/Alfredo/Documents/projects/EOSC/AAI Workgroup) instead. Task 35a03220aace (no pwd guard: Kilo noticed the missing files and stopped) and task 5f78eec8479b (brief told it to run pwd first and stop on mismatch: it did). No files changed in the wrong tree, but a less defensive brief would have let Kilo edit or commit in the wrong repository. The response also warned about 'external paths (..)' although none were in the spec. Logs: ~/.local/share/kilo-mcp/tasks/35a03220aace.log, 5f78eec8479b.log. Workaround used: kilo CLI directly, 'kilo run --dir <dir> --model ... --variant ...', which honoured the directory. Suggestion: pass the directory explicitly to the spawned kilo process (--dir) and fail the call when the resolved cwd differs from working_directory.
