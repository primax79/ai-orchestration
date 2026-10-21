# N031 kilo-mcp protected-files warning fires on a mere mention of AGENTS.md

- id: N031
- title: kilo-mcp protected-files warning fires on a mere mention of AGENTS.md
- kind: bug
- status: processed
- created: 2026-10-21T06:34:34.090714+00:00
- author: ai-coding-tools
- about: kilo-mcp/server.py _protected_paths_warning
- produced: ai-coding-tools:T021
- processed-by: ai-coding-tools

Dispatching T034, whose spec talks about the AGENTS.md that 'tasks upgrade' writes (code content, not the project-root file), kilo_implement prefixed '⚠️ PROTECTED FILES: the spec mentions AGENTS.md'. Advisory only, but noisy: it fires on any mention. Better: match edit intent near the name (create/edit/update/write AGENTS.md at the root), or only focus_files plus explicit root paths.
