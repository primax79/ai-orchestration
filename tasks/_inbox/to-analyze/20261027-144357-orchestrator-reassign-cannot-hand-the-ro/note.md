# N068 orchestrator reassign cannot hand the role to the calling interactive session; registers a phantom headless session

- id: N068
- title: orchestrator reassign cannot hand the role to the calling interactive session; registers a phantom headless session
- kind: bug
- status: ready
- created: 2026-10-27T14:43:57.958950+00:00
- author: d4science-kb-3d (d4science_kb orchestrator session)
- about: ai-orch orchestrator reassign; ai-orch sessions register; UC028
- produced: -
- processed-by: -
- short: reassign: no interactive holder

What (2026-10-27, workspace ~/works/d4science_kb): the owner declared the current interactive Claude Code session the orchestrator. Holder was gen 1, kilo, kind=interactive, status stale, turns 0.

Steps:
1. `ai-orch orchestrator reassign --tool claude --model claude-opus-5-5 --dry-run`, then the same with `--no-handoff --expect-hash <plan>` -> '[ok] Reassigned orchestrator to claude (generation 2)'.
2. The new holder f5f121da is kind=headless with provider_session_id a168b9a6-4ffd-4434-972d-2b4588434bfa: no Claude session with that id exists (~/.claude/projects/-Users-Alfredo-works-d4science-kb/ has no such transcript). The real session is 9063f48c-47d4-4079-8d84-bd8e25babd33.
3. Workaround: `ai-orch sessions register --tool claude --kind interactive --role orchestrator --provider-session-id 9063f48c-... --reason ...` -> gen 3, gen 2 retired.

Expected: reassign (or a dedicated command) can bind the role to an existing interactive session: e.g. `--kind interactive --provider-session-id <id>` or `--bind-current`, one generation bump, no phantom session. UC028 covers only the headless holder; the registry already accepts interactive holders (gen 1 was one).
Actual: two generation bumps, a retired phantom session whose resume id points to nothing (a later resume would start/fail on a non-existent session).

---
- Author: d4science-kb-3d (d4science_kb orchestrator session)
- Workspace: /Users/Alfredo/works/d4science_kb
- ai-orch: 1.1.0 (d6520d1)
- Date: 2026-10-27 14:43:57 UTC
