# N056 Doctor installs skills from a stale clone and reports outdated copies as up to date

- id: N056
- title: Doctor installs skills from a stale clone and reports outdated copies as up to date
- kind: bug
- status: processed
- created: 2026-10-25T08:54:12.511537+00:00
- author: ai-coding-tools
- about: scripts/orchestration_env.py install-skills, fetch-repos
- produced: T056
- processed-by: ai-coding-tools

Seen 2026-10-25 releasing architect-side 0.7.0: (1) install-skills reads ~/.ai-orchestration/repos/ai-orchestration, a clone still at 0.6.4 (feb6f27) days after main moved; nothing warns that the source clone is behind origin. (2) After 'env fetch-repos' updated it, install-skills still reported ~/.kilo/skills/task-pipeline and orchestration-workflow as 'already up to date' (marker source_hash 3ff02c... vs a different source file), so Kilo kept copies without the Tooling feedback and Reaching the task engine sections; only --overwrite replaced them. Expected: the up-to-date check compares the source content hash with the installed content, and the Doctor flags a source clone behind its remote (or offers fetch-repos).

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (df5d9ba)
- Date: 2026-10-25 08:54:12 UTC
