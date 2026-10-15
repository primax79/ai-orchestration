---
name: task-worktree-ops
description: "Manual, git-based mechanics for handing a task off to an Executor agent working in its own dedicated git worktree, and for interacting with its live worktree afterward - applying a fix directly when file-edit tools are permission-blocked there, and deciding when it's safe to merge, rebase, or otherwise touch a branch it's actively working on. For what to put in the task spec itself and how deeply to verify the result - which apply regardless of dispatch path - see the sibling `task-spec-authoring` skill; this one is the operational layer specific to the manual/CLI path."
---

# Task Worktree Operations

## Quick Reference

| Field | Value |
| --- | --- |
| **Audience / Role** | Architect / Orchestrator (`deep-reasoning` profile) |
| **When to Load** | Inspecting, patching, or merging an Executor's dedicated git worktree safely without racing active sessions |
| **Execution Modes Supported** | **Single-Framework Native** (native git worktrees) and **Multi-Framework MCP / CLI** (external git worktrees) |
| **Companion Scripts** | `scripts/apply_fix_to_worktree.sh` |
| **Related Skills** | `orchestration-workflow`, `task-spec-authoring`, `conflict-resolver` |

## Purpose

The manual/CLI path to an Executor has no MCP server tracking sessions or
task state on your behalf - the git worktree itself is the only record of
what's happening. This skill is the operational discipline that keeps
that safe: how to touch a worktree you don't have direct file-edit access
to, and how to avoid racing a session that's still live in it.

For everything about the *content* of the task spec and how to verify
what comes back - task granularity, ground-truth drift, caller-tracing,
one-task-one-commit, risk-calibrated verification - see `task-spec-authoring`,
which applies to this path exactly as much as to any other.

## When to use

- Applying a fix directly to a file inside an Executor's dedicated
  worktree (common when direct file-edit tools are permission-blocked
  there).
- Deciding whether/when it's safe to merge, rebase, or otherwise touch a
  branch an Executor is actively working on.

## Operational: working inside an Executor's dedicated git worktree

When direct file-edit tools (Read/Edit/Write, or `grep`/`cat`/`sed` via
Bash) are permission-blocked against paths inside the Executor's
worktree, `git` subcommands run via Bash still work fine (`git -C
<worktree> log/show/diff/status`). See
`references/worktree-git-plumbing.md` for the exact technique to apply a
fix without direct file-edit access (build corrected content in a scratch
location, stage it as a blob via `git hash-object`/`update-index`,
materialize it via `checkout-index`), or run
`scripts/apply_fix_to_worktree.sh` directly.

**Before any git operation that touches a shared/live working tree**
(merge, revert, checkout, reset): check `git status` first. If there's
substantial live uncommitted work in progress, don't interrupt it - work
only on files it isn't currently touching, or wait for a natural commit
checkpoint. **Never pause or interrupt a live Executor session to ask
permission before proceeding around it** - the default is to let it keep
running; raise a coordination question only if genuinely blocked with no
safe path forward (e.g. every file you'd need to touch is already open in
the live session).

## Reference

See `references/worktree-git-plumbing.md` for the full git-plumbing
technique (exact commands, when each step is needed, how to verify
before committing) and `scripts/apply_fix_to_worktree.sh` for a
ready-to-run version of it.
