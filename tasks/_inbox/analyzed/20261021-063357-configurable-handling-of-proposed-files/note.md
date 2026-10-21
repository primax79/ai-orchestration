# N027 Configurable handling of .proposed files

- id: N027
- title: Configurable handling of .proposed files
- kind: feature
- status: processed
- created: 2026-10-21T06:33:57.820778+00:00
- author: d4science-python-library
- about: -
- produced: ai-coding-tools:T021
- processed-by: ai-coding-tools

Every Kilo template run commits AGENTS.md.proposed; the orchestrator git mv's and recommits, and their check script fails until then. Wanted: kilo-mcp option to leave .proposed untracked, or a post-run apply when the orchestrator allows. Their top-3.
