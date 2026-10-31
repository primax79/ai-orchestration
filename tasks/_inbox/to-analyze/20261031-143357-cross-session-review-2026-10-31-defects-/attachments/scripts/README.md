# Sweep scripts (starting point for `ai-orch sweep` commands)

Origin: extractors used in the cross-session review of 2026-10-31 (about 86 Claude sessions on the Mac and the hub, 524 Kilo root
sessions, 3 stuck kilo-mcp tasks, 29 Kilo worktrees). Generalised: no workspace names or paths are hardcoded; everything is a parameter.

Rules common to all scripts: Python 3 standard library only, strictly read-only (SQLite opened `mode=ro`, git read commands only),
output on stdout (or `OUTDIR` for the digest), shared options in `_common.py` (`--since YYYY-MM-DD`, default 10 days; `--exclude SUBSTR`
repeatable, used to skip personal/unrelated paths; `--include SUBSTR` for project directories). Run with `python3 -I script.py ...`.

| Script | Reads | Outputs | Candidate sweep command |
| --- | --- | --- | --- |
| `transcript_inventory.py` | Claude Code transcripts (`~/.claude/projects/*/*.jsonl`) | TSV: project dir, session id (8 chars), mtime, size, user turns, first user message | `ai-orch sweep sessions` (which sessions were active, in which workspace) |
| `transcript_digest.py` | same | one text digest per project: user messages, last assistant messages, outgoing and incoming cross-session messages, Agent launches with "result seen" flag, open-work phrases (regex via `--phrases`). Secret-looking strings redacted; tool results never printed | `ai-orch sweep pending --explain` (feeds a model that classifies pending items) |
| `transcript_lastmsgs.py` | one transcript | last N assistant messages and last user message | helper for the above |
| `kilo_session_refs.py` | transcripts | TSV: Kilo session ids (`ses_...`) mentioned in any transcript, with the projects mentioning them (proxy for "a coordinator saw this run") | `ai-orch sweep delegations` (uncollected runs) |
| `kilo_runs.py` | Kilo SQLite DB (`~/.local/share/kilo/kilo.db`) | TSV: one row per root session: directory, title, agent, model, cost, times, message count, finish reason, last part status, tool errors, open todos, children, git branch + dirty | `ai-orch sweep kilo` (runs that ended mid-run or errored) |
| `worktree_state.py` | TSV from `kilo_runs.py` + git | TSV per worktree: branch, dirty files, default branch, commits ahead, merged yes/no, last commit date; for unmerged ones also unpushed count, remote ref present, last subject | `ai-orch sweep worktrees` (leftovers; extends UC035 cleanup) |
| `kilo_report.py` | the three TSVs above + Kilo DB | markdown table of runs that did not end clean, with transcript reference and worktree state | report renderer |
| `kilomcp_tasks.py` | kilo-mcp task store (`~/.local/share/kilo-mcp/tasks/*.json`) + queue lock file + git | counts by status; queue lock pid alive; non-completed tasks with branch exists / merged / pid alive; failed or cancelled tasks never retried in the same directory | `ai-orch sweep kilo-mcp` (stuck running, stale lock, unreliable status) |

Typical run (Mac or hub, same commands):

```sh
python3 -I kilo_runs.py --since 2026-10-21 --exclude personal > runs.tsv
python3 -I worktree_state.py runs.tsv > worktrees.tsv
python3 -I kilo_session_refs.py --since 2026-10-21 > refs.tsv
python3 -I kilo_report.py runs.tsv refs.tsv worktrees.tsv > unclean.md
python3 -I kilomcp_tasks.py --since 2026-10-21 > kilomcp.txt
python3 -I transcript_digest.py ./digests --since 2026-10-21
```

Known limits (inherited, to fix when productised):
- The Kilo DB schema (`session`, `message`, `part`, `todo`) and the kilo-mcp task JSON fields (`status`, `pid`, `working_directory`,
  `isolated_branch`, `result`) were read as found; they are not a stable contract. The sweep should go through kilo-mcp and the
  sessions registry where those expose the data.
- Transcript digests quote conversations: the product version must store only ids, counts and pointers, never message text.
- "Worktree" is detected by path markers; the product version should use `git worktree list` per registered repository.
- Subagent completion cannot be read from the parent transcript (the tool result only acknowledges the launch); an agent run
  registry is needed for that (lesson M3).
- Host awareness is missing: each run covers one host; the product version must merge Mac and hub views per canonical copy.
