# N074 Orchestrator role per project, not per workspace

- id: N074
- title: Orchestrator role per project, not per workspace
- kind: feature
- status: processed
- created: 2026-10-27T23:00:44.757887+00:00
- author: ai-coding-tools
- about: -
- produced: spec orchestrator-role-per-project
- processed-by: ai-coding-tools-87

Owner 2026-10-28: 'gli orchestrator sono per progetto'. Today the model is one orchestrator role per workspace (specs: events-and-triggers.md:53 'one per workspace', orchestration-broker-mcp.md:20 'workspace: one headless orchestrator role; the mail address'); 'sessions register' and 'orchestrator *' accept only --workspace.

What went wrong (2026-10-27/28, workspace ai-coding-tools): ai-coding-tools-87 orchestrates ai-orchestration and ai-swissknife, ai-coding-tools-58 orchestrates git-code-rag. Asked to take over 'the stalled work', 58 registered as orchestrator and took the whole workspace role from 87 (gen 4), then had to give it back (gen 5). With one role per workspace, two legitimate orchestrators of different projects cannot both be registered; the UI, mail and handoff show only one of them.

Proposal (needs the owner's confirmation on point 1):
1. Role scope = (workspace, project). Each registered project has its own orchestrator role, holder, generation, queue, cursor and mail address (workspace:project). The _workspace project keeps a role for cross-project coordination (workspace tasks, inbox triage), optional.
2. A session may hold the role in several projects (87 holds ai-orchestration and ai-swissknife); 'sessions register --role orchestrator --project P' (repeatable or a list), default project from the cwd (nearest registered project), never silently the whole workspace.
3. 'orchestrator status' lists every project's holder; 'orchestrator status --project P' for one. Succession/reassign/hand-off take --project. Taking a role held by a live session needs --force plus a reason, and notifies the holder (mail).
4. Events and triggers route to the project's orchestrator (task events carry the project already); peer messages to 'workspace:project' reach that project's holder.
5. UI / VS Code: holder shown per project in the project view; the workspace view lists all holders.
6. Migration: the current workspace role becomes the role of _workspace (or of the project the holder declares); registries with one project are unchanged in practice.
Related: N068 (orchestrator reassign cannot bind the calling interactive session).

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (b0cd978)
- Date: 2026-10-27 23:00:44 UTC

## Owner decision (2026-10-28)

- Point 1 confirmed: there is an orchestrator role **per project**. When a project has no orchestrator of its own,
  the **workspace orchestrator** handles it (fallback). ai-coding-tools-58 (orchestrator of git-code-rag) and
  ai-coding-tools-87 (orchestrator of ai-orchestration and ai-swissknife) are to align on the detailed spec.
