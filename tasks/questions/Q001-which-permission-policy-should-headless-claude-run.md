# Q001 Which permission policy should headless Claude runs use by default, per mode

- id: Q001
- question: Which permission policy should headless Claude runs use by default, per mode?
- status: answered
- blocks: -
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-17
- origin-run: -
- open-answer: yes
- recommended: A
- applied: yes
- short: Headless Claude permissions

## Context

Headless Claude runs (`claude -p`) cannot show permission prompts. The run engine (initiative 07) launches them with `--permission-mode acceptEdits --permission-prompts none`: file edits are allowed, but every tool that would normally prompt is denied, including Bash outside an allow-list and MCP tools. Without an allow-list an `execute` run cannot run tests or `git commit`, and an `orchestrate` run cannot call kilo-mcp.

Today 07.3 refuses to launch Claude when no `allowed_tools` is configured for the mode, so nothing unsafe happens by default; but runs are unusable until this is decided.

Where it applies: `execute` runs work in an isolated git worktree (writes are contained to that worktree, but Bash can still reach the rest of the machine); `verify` runs work in a throwaway detached worktree; `orchestrate` runs work in the main workspace and need MCP tools (kilo-mcp) and git.

The setting lives in `orchestration.toml` under `[tools.claude.headless]` (per mode), and the Run dialog shows it; a dangerous mode is shown in red.

## Options

- **A** — Per-mode allow-list: execute and verify get Bash(git:*), test runners (pytest, npm test, uv run) and file tools; orchestrate also gets the kilo-mcp tools. Safe, but a run stalls on anything not listed (visible in its log).
- **B** — Broad allow-list: Bash(*) plus all MCP tools, still with acceptEdits. Runs never stall on permissions, but any shell command is allowed on this machine.
- **C** — bypassPermissions for execute/verify (inside worktrees only), allow-list A for orchestrate: simplest for executors, full machine access for those runs.

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-17
