# N081 Multi-host orchestration: Mac orchestrator plus local orchestrators on a dev server

- id: N081
- title: Multi-host orchestration: Mac orchestrator plus local orchestrators on a dev server
- kind: feature
- status: processed
- created: 2026-10-29T21:53:00.412835+00:00
- author: claude (ricerca_auto architect session)
- about: /Users/Alfredo/works/ricerca_auto; N078; N079; N080
- produced: specs/multi-machine-development-architecture.md (+ review 2026-10-29), initiative 19, UC038-UC040, T087
- processed-by: claude (ai-coding-tools session, 2026-10-29)

## What

ai-orchestration is single-host by design; the owner now develops on two machines (Mac: top-level orchestrator; dev server alf_ubuntu: local orchestrators and executors in GNU screen + git worktrees) and needs it to support that.

## Gaps found (analysis of the repo, 2026-10-29)

1. No host identity anywhere: task headers, `run.json`, session records, workspace registry, events. Remote work is an explicit non-goal in specs (orchestration-broker-mcp §8 "v2: other machines", peer-messaging §9, agent-runs-from-ui §10).
2. No claim/lease on tasks; concurrency is local `fcntl.flock` + `--expect-task-hash`, invisible across machines.
3. Orchestrator role, generation and fencing token live in git-excluded `.ai-orchestration/` per host: two machines would both believe they hold the role; no cross-host handover.
4. `ai-orch run`: setsid supervisor, pid-based `reconcile()` (a run on another host would be marked `lost`), worktrees in `../.worktrees/<repo>/<run_id>` (not `.kilo/worktrees/<task>`), no screen/tmux backend, no ssh dispatch. kilo-mcp has a separate, also local, task store.
5. No non-blocking question channel for a running executor (questions only via final-message blocks; 16.7/16.8 open and same-machine by spec).
6. No toolchain preflight of the target (bun, node, project venv): `env status` checks only assistant CLIs. Real case: T205 in ricerca_auto was dispatched to alf_ubuntu where bun is missing.
7. Config location inconsistency: rendered AGENTS.md and QUICKSTART say `tasks/orchestration.toml`, code reads `.ai-orchestration.local.toml` or `~/.config/ai-orchestration/projects/<dir>/orchestration.toml`.
8. `ai-orch describe` lists only part of `run` subcommands.

## What already fits (build on it)

Git-versioned `tasks/` (headers, state machine, `questions/`, `_inbox`, index merge driver) already travels between machines; `executor: session:<name>|workspace:<slug>`, `branch`, `worktree`, `run-id`, `waiting-on`, `verify-by`; `[tasks] extension_fields` can add `host`/`claimed-by` without code; fenced succession + handoff prompt are the right primitives to extend; `[tools.*.headless] argv` is the only seam for an ssh/screen wrapper. Each machine can run its own local broker/orchestrator.

## Requested

A design (spec + initiative) for multi-host: host identity in tasks/runs/sessions/registry, task claim/lease visible across machines (via git-tracked state or the common registry N079), cross-host role handover with fencing, a screen/tmux run backend and ssh dispatch (or a per-host agent that the broker talks to), a non-blocking executor question channel, target toolchain preflight. Related: N078, N079, N080.

## Decisions by the owner (2026-10-29) — these simplify the design

1. **Hub, not peers.** alf_ubuntu (always on) is the center; the Mac and any future machine are clients. Registry, broker, console backend live on the hub; clients reach them through the ssh tunnel. No cross-host lock service or peer role handover is needed.
2. **Durable state stays in git, with a single master.** Task state in git is fine (it is what we do today); the races came only from having two writable masters (Mac and server repos pushing to each other with `updateInstead`). With one bare reference repo on the hub, claiming a task = pull, edit header (`state`, `host`), commit, push; a rejected non-fast-forward push is the compare-and-swap: the loser pulls, sees the claim, picks another task. No distributed locks.
3. **Live state is per host.** Runs, screen sessions, processes, logs stay on the machine that runs them; the console reads them from each host (ssh). Only this part needs per-host collection.

Consequence for the gaps listed above: points 2 and 3 (claims, cross-host role) reduce to "single reference repo + host field + push-as-CAS"; the remaining work is host identity, a screen run backend with standard names, per-host live-state collection for the console, non-blocking questions, toolchain preflight.
