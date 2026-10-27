# N069 config show ignores the current directory; reassign dry-run diff hides the external target path

- id: N069
- title: config show ignores the current directory; reassign dry-run diff hides the external target path
- kind: bug
- status: ready
- created: 2026-10-27T14:43:58.756295+00:00
- author: d4science-kb-3d (d4science_kb orchestrator session)
- about: ai-orch config show; ai-orch orchestrator reassign --dry-run
- produced: -
- processed-by: -
- short: config show ignores cwd

1. In ~/works/d4science_kb, `ai-orch config show` prints 'Project config: None (exists=False)', while `ai-orch config show --workspace ~/works/d4science_kb` finds ~/.config/ai-orchestration/projects/d4science_kb/orchestration.toml (written by reassign). Other groups (orchestrator, sessions) default --workspace to the current directory; config show does not. Expected: same default.
2. `orchestrator reassign --dry-run` shows the diff as 'a/orchestration.toml' / 'b/orchestration.toml', which reads as a file in the repo root; the file goes to ~/.config/ai-orchestration/projects/<name>/. Expected: the diff header names the real path.

---
- Author: d4science-kb-3d (d4science_kb orchestrator session)
- Workspace: /Users/Alfredo/works/d4science_kb
- ai-orch: 1.1.0 (d6520d1)
- Date: 2026-10-27 14:43:58 UTC
