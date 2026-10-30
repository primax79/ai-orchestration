# N086 Friction adopting the hub executor scripts in another project (ricerca_auto)

- id: N086
- title: Friction adopting the hub executor scripts in another project (ricerca_auto)
- kind: request
- status: ready
- created: 2026-10-29T23:19:58.811034+00:00
- author: claude (ricerca_auto architect session)
- about: ai-orchestration .tmp/executors; initiative 19; ricerca_auto scripts/agents
- produced: -
- processed-by: -
- short: Friction adopting hub executor

## Friction adopting the hub executor pattern in ricerca_auto (2026-10-30)

Adapted `.tmp/executors/{launch.sh,brief-common.md,chain.sh}` into ricerca_auto `scripts/agents/` (commit b2b5a76 there). What had to change or bit us, as input for 19.6 (screen backend), 19.7 (preflight) and the chain logic:

1. **Hard-coded repo, paths and test command.** launch.sh/chain.sh embed the ai-orchestration repo path, `main`, and `uvx pytest ./scripts ./plugins`. ricerca_auto uses `master` and runs tests one process per file (`PYTHONPATH=backend:. python tests/<file>`, ~10 min for 113 files); a pytest single-process run gives 117 failures + 31 errors that are not real. The test command, its mode (single run vs per file) and the expected duration must be per-project config, and the baseline must be in the same format.
2. **Baseline is per file, not per test** in a per-file project: chain compares failing test files against `.tmp/baseline-perfile.txt`. 38/112 files already fail on ricerca_auto master (T210 there); without a baseline every verification is red or, worse, executors claim green on a subset.
3. **stdin swallowed in `ssh host 'bash -s' <<EOF` scripts**: `kilo run` and `docker compose exec` read the rest of the heredoc as their stdin, silently truncating the script. Launchers/remote helpers must run them with `</dev/null`.
4. **Log redirect before mkdir**: starting `chain.sh` in screen with `>> .tmp/executors/chain.screen.log` exits immediately when the folder does not exist yet (the script's own mkdir runs too late). Create the folder in the launcher or log inside the script only.
5. **Executors with `--auto` change the host**: T205's Kilo ran `npm install -g bun` (and symlinked it into ~/.local/bin) because bun was missing. The brief now forbids it, but only a preflight (19.7) plus a dedicated low-privilege user prevents it.
6. **Runs started before the pattern existed** (screen `t205-auth`, worktree `.kilo/worktrees/t205`, no `.status` file): chain needs per-entry screen name/worktree and "screen gone" as completion when there is no status file. Adoption of a running task should be supported, not require a relaunch.
7. **Delivery check**: ricerca_auto executors set `state: delivered` in their task file on their branch (project convention); the chain checks that header instead of a separate Final Report file. Worth making the delivery signal configurable until `run mark-delivered` (§10.5) exists.

---
- Author: claude (ricerca_auto architect session)
- Workspace: /Users/Alfredo/works/ricerca_auto
- ai-orch: 1.1.0 (2965604)
- Date: 2026-10-29 23:19:58 UTC
