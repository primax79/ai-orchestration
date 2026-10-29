# N078 No upgrade path for projects already using ai-orchestration

- id: N078
- title: No upgrade path for projects already using ai-orchestration
- kind: feature
- status: processed
- created: 2026-10-29T21:49:22.154149+00:00
- author: claude (ricerca_auto architect session)
- about: /Users/Alfredo/works/ricerca_auto
- produced: specs/multi-machine-development-architecture.md (+ review 2026-10-29), initiative 19, UC038-UC040, T087
- processed-by: claude (ai-coding-tools session, 2026-10-29)

## What

There is no upgrade path for projects that already use ai-orchestration. The tool evolves (592 commits in ai-orchestration since 2026-10-15), but nothing tells a consuming project that it has fallen behind, and nothing migrates it to the current conventions.

## Evidence (project /Users/Alfredo/works/ricerca_auto, 2026-10-29)

- `AGENTS.md` last regenerated on 2026-10-17 (commit 94f31dd); the file now contains the old hand-written version followed by the rendered block (duplicated content).
- No `tasks/orchestration.toml`.
- The workspace is not in the registry (`ai-orch workspace list` does not show it).
- `tasks/00-INDEX.md` has no generated-region markers: `ai-orch tasks sync-index` fails with "Index has no generated-region markers ... Run with --adopt"; the session then edited the index by hand instead of adopting it.
- Sessions in the project kept using the older direct tools (kilo-mcp, ad-hoc `screen` + `kilo run` over ssh) and did not use `run`, `sessions`, `orchestrator`, `questions`, `triggers`, because nothing surfaced that they existed or that the project was out of date.

## Expected

1. A way to detect drift: e.g. `ai-orch doctor` / `ai-orch workspace check <path>` reporting the project's convention version vs the tool's (missing config, unregistered workspace, index without markers, stale rendered AGENTS.md, task header fields from older schemas), with severity.
2. Surfacing it where sessions look: a warning from any `ai-orch` command run inside a stale project, and/or a SessionStart hook / rendered AGENTS.md line telling the agent to run the check.
3. A guided migration: `ai-orch upgrade` (preview by default, plan hash, `--apply --expect-hash` like the other mutating commands) that adopts the index, writes the config, registers the workspace, re-renders AGENTS.md removing duplicated hand-written blocks, and migrates task headers; safe to run while executor worktrees are active (or refuses with a clear reason).
4. A record per project of the convention/schema version it was last migrated to, so drift is computable.

## Why it matters

The owner is about to formalize a two-machine workflow (Mac orchestrator + local orchestrators on the dev server alf_ubuntu) on top of ai-orchestration; projects that silently stay on old conventions defeat that, and agents rebuild by hand what the tool already provides.

---
- Author: claude (ricerca_auto architect session)
- Workspace: /Users/Alfredo/works/ricerca_auto
- ai-orch: 1.1.0 (2965604)
- Date: 2026-10-29 21:49:20 UTC
