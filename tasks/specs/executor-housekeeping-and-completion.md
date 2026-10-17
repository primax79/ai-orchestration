# Spec: Executor housekeeping and completion signalling (cleanup delegated to the executor)

- **Status:** DRAFT v0 (2026-10-17). Written from a real session on `ricerca_auto`; nothing here is implemented or reviewed yet.
- **Drives:** a new initiative (number to assign). Candidate tasks are in section 6.
- **Repos:** `kilo-mcp` (primitives), `ai-orchestration` (executor-contract skill, `AGENTS.md` template, `tasks_engine.py` checks)
- **Related:** [`agent-runs-from-ui`](agent-runs-from-ui.md) (run status and reconciliation), `tasks/server-and-bindings/T012-kilo-run-hangs-after-completion.md`

## 1. Why

Observed on `ricerca_auto` on 2026-10-17, after a day of parallel Kilo runs:

1. **Debris piles up.** 46 worktrees, 45 branches, about 76 Kilo sessions, all "New session" with no title, orphan Vite/uvicorn processes from removed worktrees, and 6 Agent Manager cards in `.kilo/agent-manager.json` whose worktrees no longer exist.
2. **The orchestrator cannot safely clean up.** It can run `git worktree remove` and `git branch -d` (both refuse unsafe cases), but the permission layer rightly blocks bulk `kilo session delete` and process kills: the scope cannot be verified from outside Kilo. Kilo itself, asked to do it with a keep-list, did it correctly and found the orphans.
3. **"Finished" is not visible.** `kilo_task_status` kept reporting finished runs as `WORKING (long model call in progress)`; the architect believed a delivered task had run for 47 minutes. Task files on finished branches still said `blocked` / `in progress`, because nothing forces the executor to record completion in its own branch.
4. **Leftover work hides in worktrees.** A closed task (T021) had its real result as uncommitted changes in a worktree; master lacked it. Removing the worktree would have destroyed it.

## 2. Principles

- **Cleanup belongs to the owner of the resources.** Kilo owns its sessions, worktrees and agent-manager state; the architect states intent (what to keep), Kilo executes.
- **Never destroy unverified work.** Anything dirty, unmerged, or with a live process is kept and reported, never forced.
- **Dry-run first, apply second**, with the same plan hash (as `run preview` in `agent-runs-from-ui` R1).
- **The branch is the source of truth for a run's outcome**, not the process table.

## 3. Primitive: `kilo_cleanup`

Input:
- `working_directory` (repo root)
- `keep`: explicit list of branches / worktree names / session ids that must survive
- `scope`: any of `worktrees`, `branches`, `sessions`, `processes`, `agent_manager_state` (default: all)
- `base_branch` (default: the repo default branch) — what "merged" means
- `session_max_age_hours` (optional) — only idle sessions older than this are candidates
- `dry_run` (default `true`)
- `plan_hash` (required when `dry_run=false`; from the preview)

Candidate rules (a candidate is removed only if every condition holds):
- **Worktree:** clean (`git status --porcelain` empty), its branch is merged into `base_branch` or detached at an ancestor of it, no process has it as cwd, not in `keep`. Nested worktrees (a worktree inside another worktree's directory) are removed child first.
- **Branch:** merged into `base_branch` (`git branch -d` semantics, never `-D`), not checked out anywhere, not in `keep`.
- **Session:** idle, older than `session_max_age_hours`, not attached to a running task, not the `continue_session_id` of a task in `delivered`/`bounced` state when a task registry path is given (`tasks_dir`, optional), not in `keep`.
- **Process:** only processes whose cwd or command line sits inside a worktree that is being removed (orphan dev servers: Vite/esbuild/uvicorn). Never a process outside the repo's worktrees. Terminate gracefully first, kill after a timeout.
- **Agent Manager state:** entries pointing to a worktree path that does not exist and a branch that is merged or absent.

Output (JSON): for each candidate `{kind, id, action, reason}` and for each kept item `{kind, id, kept_because}` (`dirty`, `unmerged`, `live_process`, `in_keep_list`, `needs_task_state`), plus `plan_hash`, counts, and `leftovers` (see 3.1).

### 3.1 Leftover work check (before any worktree removal)

For every worktree considered for removal, report:
- uncommitted changes (`status --porcelain`), especially renames and untracked files;
- commits not reachable from `base_branch`;
- whether its task (matched by branch name or `tasks_dir`) is closed while the changes are not on `base_branch`.

Such a worktree is **kept** and listed as `leftover_work`, with the diffstat. The architect decides (commit and merge, or discard). `kilo_cleanup` never discards it.

### 3.2 Safety

- No `--force`, no `git branch -D`, no `git clean`, no `rm -rf` of anything outside a removed worktree's own directory (and only after `git worktree remove` succeeded).
- Refuses to run if `working_directory` is not a repo root, or if `keep` contains a name that does not exist (typo guard).
- Writes an audit file `.kilo/cleanup-<timestamp>.json` with the plan and what was done.
- Idempotent: a second run with the same inputs removes nothing more.

## 4. Primitive: `kilo_task_status` reports the outcome

`kilo_task_status` / `kilo_task_wait` must not use the OS heuristic alone to say a run is working.

- Return, per task: `state` (`running`, `ended`, `unknown`), `ended_at`, and for worktree runs `branch`, `commits_ahead` of the base branch, `last_commit`, `dirty_files`, and the `state:` header of the task file **as read from the branch** (`git show <branch>:<path>`), when a task path is known.
- A process with no session activity for N minutes and a branch whose task state is `delivered` is `ended`, not `WORKING`.
- `kilo_task_progress` returns "session not found" while a run is alive; document it, or fall back to the commits.
- Relation to T012 (`kilo run` hangs after completion): `ended` is decided from the branch, so a hanging process does not hide a finished run.

## 5. Executor contract: record completion in the branch

Add to the `executor-contract` skill and to the AGENTS.md template (`tasks_engine.py` can lint it):

- In the **same final commit** as the work, the executor sets `state: delivered` and adds the `verification pending:` line in the task file, and appends a dated entry to `PROGRESS.md` (commit hash, tests run and results, known issues).
- It never marks `verified` or `done`.
- Every delegation prompt ends with this step before the Final Report. The architect-side skill (`kilo-mcp-orchestrator`) templates it.
- `ai-orch tasks validate --branch <name>` (new, optional) warns when a branch ahead of base has a task still `open`/`in progress`/`blocked`.

## 6. Candidate tasks

| # | Task | Repo | Depends on |
| --- | --- | --- | --- |
| 1 | `kilo_cleanup` dry-run (worktrees, branches, leftover check), tests on a sandbox repo | kilo-mcp | - |
| 2 | `kilo_cleanup` apply with `plan_hash`, audit file, nested worktrees, idempotence | kilo-mcp | 1 |
| 3 | `kilo_cleanup` sessions, processes, agent-manager state | kilo-mcp | 2 |
| 4 | `kilo_task_status`/`wait` outcome from the branch (section 4) | kilo-mcp | - |
| 5 | Executor completion marker: skill text, template, `validate --branch` | ai-orchestration | - |
| 6 | Orchestrator skill: the cleanup call with a keep-list, run after each release | ai-orchestration | 2 |

## 7. Open questions

- **Q1.** Do Kilo sessions record their worktree and branch, so that "session of a task still `delivered`" can be decided without a task registry? If not, a registry path argument (`tasks_dir`) is needed.
- **Q2.** Is `.kilo/agent-manager.json` safe to edit from the MCP server while the VS Code extension is open, or must the extension own that write (the Kilo session on 2026-10-17 found it protected)? If the extension owns it, `kilo_cleanup` only reports those entries.
- **Q3.** Should cleanup also run automatically after `kilo_task_result` for a merged branch (opt-in), or only when asked? Default proposal: only when asked.
- **Q4.** Does `kilo_verify_worktree` (new tool in this server) overlap with section 4? Reuse it if so.

## 8. Non-goals

- Deleting or rewriting history, remote branches, or anything outside the repo's `.kilo/` and its worktrees.
- Cleaning other projects' sessions: scope is the given `working_directory` only.
- Replacing `git worktree remove` for the architect's own integration worktrees; those it still removes itself.
