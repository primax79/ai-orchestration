# N001 projects discover refuses an unregistered workspace

- id: N001
- title: projects discover refuses an unregistered workspace
- kind: bug
- status: processed
- created: 2026-10-21T06:32:52.169218+00:00
- author: ai-coding-tools
- about: scripts/orchestration_registry.py, tasks/specs/ui-multi-project.md §1
- produced: T039
- processed-by: ai-coding-tools

Command: `ai-orch projects discover /Users/Alfredo/works/ai-coding-tools` (workspace not registered). Actual: [ERROR] "Workspace not found for argument ...". Expected (ui-multi-project.md §1, step 2): read-only discovery on an unregistered path, listing the proposed projects, so the user can see what registration would add before applying it. The VS Code 0.6.0 banner 'Projects discovered, not registered' leads straight to this.
