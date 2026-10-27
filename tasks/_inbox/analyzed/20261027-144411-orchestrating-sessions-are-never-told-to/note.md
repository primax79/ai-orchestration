# N070 orchestrating sessions are never told to register as orchestrator

- id: N070
- title: orchestrating sessions are never told to register as orchestrator
- kind: feature
- status: processed
- created: 2026-10-27T14:44:11.370587+00:00
- author: ai-coding-tools-c1
- about: -
- produced: T071
- processed-by: ai-coding-tools-c1

On 2026-10-27 the owner asked whether I (an interactive Claude session orchestrating ai-coding-tools for days) was registered: 'ai-orch orchestrator status' said role missing. Nothing in the orchestration-workflow / task-pipeline skills, the managed AGENTS.md block or the handoff prompt tells an orchestrating session to 'sessions register --role orchestrator' and heartbeat. Proposal: (1) the managed AGENTS.md block and the orchestration skill state it; (2) task-changing commands run by an unregistered session in a workspace whose role is missing print a one-line hint; (3) the UI shows 'no orchestrator' prominently.

---
- Author: ai-coding-tools-c1
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (d6520d1)
- Date: 2026-10-27 14:44:10 UTC
