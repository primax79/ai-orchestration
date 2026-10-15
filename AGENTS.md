# AGENTS.md — ai-orchestration (formerly `ai-architect-executor`)

The central repository for the **Architect/Executor orchestration pattern**, formal task/state specifications, cross-repo orchestration analysis (`docs/`), and evolution task tracking (`tasks/`).

## Core Architectural Principle: Decoupled Orchestration & Pluggable Execution

Task definition (`tasks/`), acceptance criteria (`Verification`), state transitions (`open → in progress → delivered → verified → done`), and the 6-phase Architect/Executor workflow are **strictly independent of the execution mechanism**. `ai-orchestration` supports two execution topologies equally:
1. **Single-Framework Native Mode (Zero MCP required):** e.g., **Kilo-only** (main session orchestrates parallel Kilo worktrees via `agent_manager` and subagents via `task`) or **Claude-only** (main session orchestrates parallel Claude subagents/worktrees via `Agent`), with independent verification performed by a fresh context-blind session (`independent-session`) or a different model within the same framework.
2. **Multi-Framework / External MCP Mode:** cross-framework delegation and verification (`cross-agent` / `panel`) over standalone MCP servers (`kilo-mcp`, `claude-mcp`) or CLI (`codex`).

## Start here

- **[`tasks/00-INDEX.md`](tasks/00-INDEX.md)** — Live registry of initiatives and emergent tasks (`task-pipeline` convention; see [`tasks/AGENTS.md`](tasks/AGENTS.md) and [`tasks/CONTEXT.md`](tasks/CONTEXT.md)).
- **[`docs/01-current-architecture-and-inventory.md`](docs/01-current-architecture-and-inventory.md)** — Complete inventory and technical analysis of all orchestration & task-definition skills, agents, role profiles, and bindings.
- **[`docs/02-gap-analysis-and-evolution-roadmap.md`](docs/02-gap-analysis-and-evolution-roadmap.md)** — What has been resolved from the consolidated review vs. open gaps and evolution tracks.
- **[`docs/03-task-model-and-ui-architecture.md`](docs/03-task-model-and-ui-architecture.md)** — Formalization of the task model (state machine, grammar, cross-agent verification) and architecture for the Python Core + Web UI → VS Code Extension.
- **[`docs/04-project-bootstrap-and-agents-md-pattern.md`](docs/04-project-bootstrap-and-agents-md-pattern.md)** — Analysis of the `~/works/ricerca_auto/AGENTS.md` pattern: how to instantiate and maintain project-level orchestration rules without model/rule drift.
- **[`docs/05-orchestration-config-schema.md`](docs/05-orchestration-config-schema.md)** — Unified Global + Project `orchestration.toml` configuration schema (tools, MCP servers, per-tool model matrix by activity profile, cross-agent verification routing, and `AGENTS.md` generation).
- **[`STATUS.md`](STATUS.md)** — Historical design log of the 2026-08-05 split out of `gcube-ai-toolkit`.

## Layout

- `plugins/architect-side/` — `orchestration-workflow`, `task-pipeline`,
  `orchestration-metrics`, `conflict-resolver`, `task-spec-authoring`,
  `task-worktree-ops` skills.
- `plugins/executor-side/` — `executor-contract` skill.
- `plugins/shared/` — `orchestration-setup` skill.
- `scripts/generate_binding.py` — generates a **binding** (a concrete tool
  fork of a protocol-agnostic skill here, e.g. naming real MCP tools) into
  a downstream repo.
- `scripts/regenerate_generic_skills.py` / `scripts/generate_skill_indices.py`
  — regeneration and index maintenance for this repo's own skills.

## Mandatory rules

- **Stay protocol-agnostic.** Nothing under `plugins/` may name a concrete
  tool, MCP function, or product (`kilo_implement`, etc.). If a change
  needs a concrete name to make sense, it belongs in a binding (currently
  `kilo-mcp`), not here.
- **This repo is upstream of `kilo-mcp`'s bound skills.** `kilo-mcp`
  generates `kilo-mcp-orchestrator`, `kilo-mcp-executor-contract`,
  `kilo-mcp-conflict-resolver`, and `kilo-mcp-metrics-analyst` from this repo's
  `orchestration-workflow`, `executor-contract`, `conflict-resolver`, and
  `orchestration-metrics` `SKILL.template.md` sources (via `scripts/generate_binding.py` here,
  `scripts/regenerate_bound_skills.py` there). If you edit one of those
  four skills' *methodology* (not binding-specific detail), the change
  needs to flow to `kilo-mcp` too — check whether `kilo-mcp/bindings/*.json`
  needs a matching update and whether `regenerate_bound_skills.py` needs to
  be re-run there. `task-pipeline`, `task-spec-authoring`, `task-worktree-ops`, and
  `orchestration-setup` have no bound counterpart — edit them freely,
  nothing downstream to keep in sync.
- **Skill manifest.** New/changed skills need valid YAML frontmatter
  (`name`, `description`) in `SKILL.md` — Kilo's loader silently skips a
  skill without it.
- **Regenerate indices.** After adding, removing, or renaming a skill,
  run `python3 scripts/generate_skill_indices.py` and commit the updated
  `index.json` files alongside the change.
- **`task-spec-authoring`/`orchestration-workflow` integrate directly with
  `task-pipeline`** (`plugins/architect-side/skills/task-pipeline`) for the
  `tasks/` tree and `tasks_engine.py`.
  See `plugins/architect-side/dependencies.json` for the informational,
  non-enforced record.

## Before committing

Only when explicitly asked to commit: check `git status`/`git diff` for
scope and secrets, and if a template skill listed above changed, flag to
the user that `kilo-mcp`'s bound copy may now be stale.
