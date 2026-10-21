# N006 Per-workspace default Kilo model

- id: N006
- title: Per-workspace default Kilo model
- kind: feature
- status: processed
- created: 2026-10-21T06:33:14.466796+00:00
- author: gcube-audit
- about: -
- produced: ai-coding-tools:T019
- processed-by: ai-coding-tools

Project requires google/gemini-4-argon for all Kilo work (its AGENTS.md); kilo_implement default forces passing model on every call. Wanted: a per-workspace default (e.g. from the workspace's orchestration.toml). Their top-3 change.
