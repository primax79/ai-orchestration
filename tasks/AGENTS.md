# tasks/ convention (task-pipeline + emergent tasks)

Short copy of the `task-pipeline` skill (`plugins/architect-side/skills/task-pipeline/`). Self-contained so this repository's `tasks/` tree works with or without the VS Code extension, the broker MCP server, or the `ai-orch` CLI installed.

- **Three progressive ways to use `tasks/` (no hard dependency on extension or MCP):**
  1. **Plain Markdown + Git (zero install — no extension, no MCP, no CLI required):** Every file under `tasks/` (`00-INDEX.md`, `CONTEXT.md`, `AGENTS.md`, `NN-<slug>/plan.md`, `<category>/T###-<slug>.md`, `questions/Q###-<slug>.md`, `_inbox/`) is plain Markdown. Create, edit, transition, and close (`git mv` to `tasks/done/<category>/`) files directly following the format rules below, and update the corresponding row inside the `<!-- ai-orch:generated ... -->` markers in `00-INDEX.md`.
  2. **Standalone CLI (no extension or MCP required):** Run `~/.local/bin/ai-orch tasks …` (or the stdlib-only `python3 .claude/skills/task-pipeline/scripts/tasks_engine.py …` / `python3 <path-to>/tasks_engine.py …`) to create, transition, validate (`tasks validate`), and sync (`tasks sync-index --apply`).
  3. **Broker MCP / Web UI / VS Code Extension (when installed):** Use the `ai-orchestration` MCP tools (`tasks.*`, `questions.*`, `inbox.add_note`) or the UI dashboard.
- **Cross-framework skill loading (any AI assistant / framework):** Claude Code loads `.claude/skills/` and Kilo Code loads `.kilo/skills/`. Any other AI coding framework or assistant (Codex, Gemini CLI, Copilot, Cursor, etc.) that reads `AGENTS.md` without native `.claude/skills/` discovery MUST read the project-versioned orchestration skills directly from `.claude/skills/<skill>/SKILL.md` (specifically `.claude/skills/task-pipeline/SKILL.md`, `.claude/skills/orchestration-workflow/SKILL.md`, `.claude/skills/task-spec-authoring/SKILL.md`, `.claude/skills/executor-contract/SKILL.md`) and use `python3 .claude/skills/task-pipeline/scripts/tasks_engine.py` when `ai-orch` is not on `PATH`.
- **Pipeline for large multi-task initiatives:** `_inbox/to-analyze/` → `specs/<slug>.md` → `NN-<slug>/plan.md` (tasks `### NN.T - <title>` followed by `- **Status:** \`<state>\` · ...`, sized one-per-commit, inline or expanded) → `done/NN-<slug>/` (with `summary.md`) → `merged/NN-<slug>/`.
- **Emergent tasks (`<category>/T###-<slug>`): Capture first, then continue.** Work that appears mid-session becomes a task file at once; it does not stay in the session context.
- **Ids & citations:** `T###`, unique across `done/` too; reserve the id by creating the file immediately. Always cite tasks and questions as `ID (short title)` (or `project/ID (short title)` across projects).
- **Layout:** `tasks/<category>/T###-<slug>.md` for small tasks; `T###-<slug>/{README,CONTEXT,PROGRESS}.md` when there is context. Each category has a `README.md` and `notes/`.
- **Header (closed set, exact order, `- key: value` lines under `# T### <title>`, empty value is `-`):** `id`, `title`, `category`, `priority` (P0-P3), `priority-reason`, `next-up` (`yes`|`no`), `state`, `executor`, `depends-on`, `decider`, `sources`, `paths`, `handoff`. Optional extensions (after `handoff`): `profile`, `verification-mode`, `verifier`, `size`, `kind`, `labels`, `branch`, `worktree`, `run-id`, `use-cases`, `short`, `conditions`. Required body sections: `## Goal`, `## Steps`, `## Verification`.
- **Microtasks (`tasks/micro/T###-<slug>.md`):** reduced header in exact order (`id`, `title`, `kind`, `priority`, `state`, `executor`, `paths`, `depends-on`, `size`, `labels`, optional `short`); size defaults to `XS`; body section `## What` only.
- **States:** `open`, `in progress`, `paused`, `waiting`, `blocked`, `delivered`, `bounced`, `verified`, `done` (or `done with a caveat`), `dropped`. No direct `open`/`in progress` → `done` (always pass through `delivered`). `verified` is set by someone other than the executor, or by the executor after the owner's explicit approval (recorded in `PROGRESS.md`).
- **Registry:** `00-INDEX.md` (Initiatives, Specs, Next up <= 5, Tasks by category, Decisions waiting, Done) is the state; keep it current with every change.
- **Done:** `git mv` the finished emergent task to `tasks/done/<category>/`.
- **Several sessions:** only a category's `owner-session` edits its tasks; others add notes or new tasks.
- **Tooling feedback:** when `ai-orch` is installed, report friction, defects, or improvements at once with `ai-orch feedback --kind bug|feature|idea|request --title "..." --body "..."` (without `ai-orch`, drop a Markdown note in `tasks/_inbox/to-analyze/`). Do not work around tooling issues silently; maintainers triage notes into tasks.

## Project settings

Content language of this registry (owner convention 2026-10-27): tasks and questions in Italian, use cases in
English. Section headings and header field names stay English: they are the format's fixed keywords.

```toml
[tasks]
language = "it"

[questions]
language = "it"

[use_cases]
language = "en"
```

<!-- ai-orch:managed begin -->
## task-pipeline managed convention

Short copy of the `task-pipeline` skill (`plugins/architect-side/skills/task-pipeline/`). Self-contained so this repository's `tasks/` tree works with or without the VS Code extension, the broker MCP server, or the `ai-orch` CLI installed.

- **Three progressive ways to use `tasks/` (no hard dependency on extension or MCP):**
  1. **Plain Markdown + Git (zero install — no extension, no MCP, no CLI required):** Every file under `tasks/` (`00-INDEX.md`, `CONTEXT.md`, `AGENTS.md`, `NN-<slug>/plan.md`, `<category>/T###-<slug>.md`, `questions/Q###-<slug>.md`, `_inbox/`) is plain Markdown. Create, edit, transition, and close (`git mv` to `tasks/done/<category>/`) files directly following the format rules below, and update the corresponding row inside the `<!-- ai-orch:generated ... -->` markers in `00-INDEX.md`.
  2. **Standalone CLI (no extension or MCP required):** Run `~/.local/bin/ai-orch tasks …` (or the stdlib-only `python3 .claude/skills/task-pipeline/scripts/tasks_engine.py …` / `python3 <path-to>/tasks_engine.py …`) to create, transition, validate (`tasks validate`), and sync (`tasks sync-index --apply`).
  3. **Broker MCP / Web UI / VS Code Extension (when installed):** Use the `ai-orchestration` MCP tools (`tasks.*`, `questions.*`, `inbox.add_note`) or the UI dashboard.
- **Cross-framework skill loading (any AI assistant / framework):** Claude Code loads `.claude/skills/` and Kilo Code loads `.kilo/skills/`. Any other AI coding framework or assistant (Codex, Gemini CLI, Copilot, Cursor, etc.) that reads `AGENTS.md` without native `.claude/skills/` discovery MUST read the project-versioned orchestration skills directly from `.claude/skills/<skill>/SKILL.md` (specifically `.claude/skills/task-pipeline/SKILL.md`, `.claude/skills/orchestration-workflow/SKILL.md`, `.claude/skills/task-spec-authoring/SKILL.md`, `.claude/skills/executor-contract/SKILL.md`) and use `python3 .claude/skills/task-pipeline/scripts/tasks_engine.py` when `ai-orch` is not on `PATH`.
- **Pipeline for large multi-task initiatives:** `_inbox/to-analyze/` → `specs/<slug>.md` → `NN-<slug>/plan.md` (tasks `### NN.T - <title>` followed by `- **Status:** \`<state>\` · ...`, sized one-per-commit, inline or expanded) → `done/NN-<slug>/` (with `summary.md`) → `merged/NN-<slug>/`.
- **Emergent tasks (`<category>/T###-<slug>`): Capture first, then continue.** Work that appears mid-session becomes a task file at once; it does not stay in the session context.
- **Ids & citations:** `T###`, unique across `done/` too; reserve the id by creating the file immediately. Always cite tasks and questions as `ID (short title)` (or `project/ID (short title)` across projects).
- **Layout:** `tasks/<category>/T###-<slug>.md` for small tasks; `T###-<slug>/{README,CONTEXT,PROGRESS}.md` when there is context. Each category has a `README.md` and `notes/`.
- **Header (closed set, exact order, `- key: value` lines under `# T### <title>`, empty value is `-`):** `id`, `title`, `category`, `priority` (P0-P3), `priority-reason`, `next-up` (`yes`|`no`), `state`, `executor`, `depends-on`, `decider`, `sources`, `paths`, `handoff`. Optional extensions (after `handoff`): `profile`, `verification-mode`, `verifier`, `verify-by`, `size`, `kind`, `labels`, `branch`, `worktree`, `run-id`, `use-cases`, `short`, `conditions`. Per-project extra fields after `handoff` can be declared via `[tasks] extension_fields = ["area"]` in `orchestration.toml` (or `.ai-orchestration.local.toml`), a fenced `toml` block in `tasks/AGENTS.md`, or a prose/bullet line ``Extra header fields: `area` `` (with or without bold, comma or `and` separated) in `tasks/AGENTS.md`. Required body sections: `## Goal`, `## Steps`, `## Verification`. Section headings (`## Goal`, `## Steps`, `## Verification`, `## Log`; question `## Context`, `## Options`, `## Answer`, `## Notes`; use-case `## Description & Business Value`, `## Preconditions`, `## Scenario / Interaction Steps`, `## Automated Verification Command`, `## Acceptance Criteria`, `## AI Validation Log`) and header field names are fixed English keywords: never translate them.
- **Content languages (per-project, versioned in `tasks/AGENTS.md`):** Declare the prose language for tasks, questions to the owner, and use cases in a fenced `toml` block in `tasks/AGENTS.md`: `[tasks] language = "en"`, `[questions] language = "it"`, `[use_cases] language = "en"` (use cases follow `[tasks] language` unless `[use_cases] language` is set; default `en`). Language settings govern only the prose content written by sessions; section headings and header field names are fixed English keywords and are never translated.
- **Microtasks (`tasks/micro/T###-<slug>.md`):** reduced header in exact order (`id`, `title`, `kind`, `priority`, `state`, `executor`, `paths`, `depends-on`, `size`, `labels`, optional `short`); size defaults to `XS`; body section `## What` only.
- **States:** `open`, `in progress`, `paused`, `waiting`, `blocked`, `delivered`, `bounced`, `verified`, `done` (or `done with a caveat`), `dropped`. No direct `open`/`in progress` → `done` (always pass through `delivered`). `verified` is set by someone other than the executor, or by the executor after the owner's explicit approval (recorded in `PROGRESS.md`).
- **Registry:** `00-INDEX.md` (Initiatives, Specs, Next up <= 5, Tasks by category, Decisions waiting, Done) is the state; keep it current with every change.
- **Done:** `git mv` the finished emergent task to `tasks/done/<category>/`.
- **Several sessions:** only a category's `owner-session` edits its tasks; others add notes or new tasks.
- **Tooling feedback:** when `ai-orch` is installed, report friction, defects, or improvements at once with `ai-orch feedback --kind bug|feature|idea|request --title "..." --body "..."` (without `ai-orch`, drop a Markdown note in `tasks/_inbox/to-analyze/`). Do not work around tooling issues silently; maintainers triage notes into tasks.
- **Effective project content languages:** Content language: tasks `it`, questions `it`, use cases `en`. Section headings and header field names are fixed English keywords: never translate them.
<!-- ai-orch:managed end -->
