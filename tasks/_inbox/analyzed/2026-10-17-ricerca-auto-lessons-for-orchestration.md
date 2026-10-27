# Lessons from a full day of Architect/Executor work on ricerca_auto (2026-10-17)

Source: the Architect session of `/Users/Alfredo/works/ricerca_auto` (Claude, driving Kilo through kilo-mcp, about 45 tasks dispatched and closed in a day, up to 8 Kilo runs in parallel). Raw observations with evidence, for the session developing ai-orchestration to turn into specs or tasks. It extends `tasks/specs/executor-housekeeping-and-completion.md` (sections 1 to 8), which already exists; items already covered there are only referenced.

## A. Executors die mid-work and the tooling hides it (new)

- **Evidence.** Three Kilo runs (T076, T077, T081) ended with status `failed` after 40 minutes with uncommitted work in their worktrees (3 to 9 modified files, 0 commits). Run logs end with `Error: unknown certificate verification error` or `Error: Network connection failed`. One run had completed 3 of 5 steps. The Architect only noticed after 39 minutes because it watched commits and `kilo_task_status`, which kept saying nothing useful.
- **Asks.**
  1. `kilo_task_status`/`kilo_task_wait` must return `status: failed|completed|running`, the last error line, the time of the last activity, and for worktree runs `commits_ahead`, `dirty_files`, `last_commit_age`. A run that failed with dirty files is `failed_with_uncommitted_work` and says so.
  2. A resume primitive: `kilo_resume(task_id)` (or `kilo_implement(continue_in_worktree=...)`) that restarts a failed run in the same worktree with a generated preamble: "a previous run was interrupted; run `git status` and `git diff`, keep what is good, commit it, finish the task", plus the original spec. The Architect did this by hand three times with a hand-written prompt; the wording worked.
  3. Delegation prompt template rule (executor-contract and kilo-mcp-orchestrator skills): "commit after every green step, never hold more than one step uncommitted", because runs are interrupted by network errors. Without it the work survives only as a dirty tree.
  4. Possible correlation with the number of parallel runs (all three failures happened with 6 to 8 concurrent runs, none with 1 to 4). Unproven. A configurable `max_concurrent_runs` with a queue in kilo-mcp would let the Architect test it.

## B. Status and progress tools mislead (new)

- `kilo_task_status` reports `WORKING - connected to the model API (long model call in progress)` for runs that had already finished (a delivered task looked "47 minutes running"); the OS heuristic cannot see the end. The process-table grep the Architect used (`ps aux | grep "kilo run"`) returned 0 while runs were alive and was useless.
- `kilo_task_progress` answers `no matching Kilo session was found yet` for the whole life of a run on some runs; once a run ends it says `already ended (status: ...)`. A reliable `ended` signal in `kilo_task_status` removes the need to call two tools.
- Same fix as A1: decide `ended` from the branch and the log, not from the process.

## C. `kilo_task_result` / `kilo_task_wait` outputs overflow the context (new)

- Typical result size 100,000 to 390,000 characters (the whole stderr trace: every tool call and every test run). The harness refuses it as over the token limit and saves it to a file; the Architect then needs `jq -r .result file | awk '/^## Final Report/{f=1} f'` every time, and when the final report is absent (failed run) `tail -c 2500`.
- Ask: `kilo_task_result(task_id, final_report_only=true)` (default true) returning only the `## Final Report` section (or the last N lines when absent) plus the path of the full log; same for the result embedded in `kilo_task_wait`.
- The prompts' "Final Report" template is echoed back as the first match of the awk filter (`## Final Report (mandatory)` inside the prompt): the executor's report must be delimited by a unique marker.

## D. Completion marker and branch state (partly in the spec, section 5)

- Confirmed need: finished branches had `state: blocked` or `in progress` in the task header. After the Architect added "set `state: delivered` and a `verification pending:` line in the final commit" to every prompt, all later deliveries carried it and the Architect could read the real state with `git show <branch>:<task file>`.
- New: `ai-orch tasks transition ... verified|done` should drop the `verification pending:` line itself; the Architect removed it with `sed -i '' '/^verification pending:/d'` on every closure (about 15 times).
- New: when a task becomes `done`, tasks whose `depends-on` are all `done` and that are `blocked` should be offered for `blocked -> open` (a `ai-orch tasks unblock-ready` command or an automatic suggestion in `transition`'s output). Done by hand 4 times today.
- New: `ai-orch tasks list` should have a `--branches` view: per active task, its branch, commits ahead, dirty files and the task state as written on the branch. This is the table the Architect rebuilt manually every time someone asked "how is it going".

## E. Integration pattern that worked (document in the orchestrator skill)

1. Create an integration worktree from the default branch, try `git merge --no-ff <task branch>`.
2. If it merges cleanly: run all tests, build, verify in a real browser on a throwaway copy of the production DB, then `git merge --ff-only integration/...` into the default branch.
3. If it conflicts: `git merge --abort`, remove the worktree, and send the exact list of conflicting files and the semantic intent of both sides back to the executor of the branch, with "merge the default branch INTO your branch, resolve keeping both behaviors, run all tests, commit the merge, mark delivered". Four such round trips today all came back correct. The default branch never held conflict markers after the first incident (the live dev server runs with `--reload`: a merge with markers on the default branch broke it for a few minutes).
- A generic helper would remove the repetition: `kilo_sync_branch(worktree, base_branch, intent)` that builds this prompt.

## F. Architect-side verification kit (project-agnostic pattern)

Every verification repeated the same 6 steps: throwaway database from a dump of the live one, backend on a free port against it, build the frontend, browser checks, teardown, ff-merge. A reusable script template per project (`scripts/verify_stack.sh <worktree> <port>`) and a section in the orchestrator skill would save many tokens. Also: never use accessibility snapshots on large pages (a 20k-token dump); use targeted `page.evaluate` and screenshots.

## G. Permissions friction (partly in the spec, sections 1 and 2)

- The permission classifier blocked, even after the owner said "go": bulk `kilo session delete`, `scripts/check_schema_drift.py --i-know-this-is-live` (read-only), deleting a phantom session on the live DB. The owner's decision was to delegate cleanups to Kilo with a keep-list (Kilo did it correctly and found orphan processes and Agent Manager cards). A `kilo_cleanup` primitive (spec section 3) is the clean answer; until then the orchestrator skill should say: "ask the owner for an allow rule or delegate the cleanup to the executor with an explicit keep-list; do not retry or work around the block".
- The executor-contract skill should require executors to avoid printing secrets found in the environment (the Architect once printed a Gemini key from a process listing).

## H. Use-case driven validation (relates to initiative 15)

- The owner asked for "all the use cases of how a user can use the portal given the features we offer". The Architect wrote `docs/use-cases-search.md` in ricerca_auto (UC ids, goal, flow, variants, errors, status per use case with task references, a gaps section, open questions) and derived tasks from the gaps (a P0 bug and an E2E acceptance suite). It is a real, small example of the spec -> use case -> test chain that `specs/use-case-management-and-ai-validation.md` describes; useful as a worked example, and the format (status legend: verified in browser / works unverified / in progress with task / gap) may be worth adopting.
- Lesson: writing the use cases exposed 5 real gaps in an hour that daily verification had not (for example, the ineligible list showing ads of other models, a portal failing silently).

## I. Smaller notes

- `kilo_implement` with `isolation='worktree'` and a pre-existing branch name collides; using fresh branch names per run avoided it.
- `kilo_metrics` reports `avg duration: 0s`; the Architect could not use it to see how long runs take.
- The zsh pitfalls cost many tool calls: unmatched globs abort the whole command (`no matches found`), `set --` with a space-containing pair, and `sed -i` needs `-i ''` on macOS; the skills should show portable forms (`find`, python for multi-line edits).
- Sessions of Kilo are all titled `New session - <timestamp>`; a title derived from the task id (`T076 resume`) would make cleanup and attribution possible without a registry.

---
**Smistata il 2026-10-27 (ai-coding-tools-d8, T078).** Analisi: `tasks/_reviews/2026-10-27-ricerca-auto-lessons-triage.md`
(23 richieste: 9 fatte, 9 in parte, 5 no). Task creati: T037, T038, T039 (kilo-mcp, registro del workspace),
T080 (contratto esecutore), T081 (branch e sblocco dipendenti), T082 (pattern di integrazione nella skill).
