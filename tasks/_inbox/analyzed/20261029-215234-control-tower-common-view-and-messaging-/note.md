# N080 Control tower: common multi-machine view and messaging across orchestrator instances

- id: N080
- title: Control tower: common multi-machine view and messaging across orchestrator instances
- kind: feature
- status: processed
- created: 2026-10-29T21:52:34.282222+00:00
- author: claude (ricerca_auto architect session), requirement from the owner
- about: /Users/Alfredo/works/ricerca_auto; N078; N079
- produced: specs/multi-machine-development-architecture.md (+ review 2026-10-29), initiative 19, UC038-UC040, T087
- processed-by: claude (ai-coding-tools session, 2026-10-29)

## What (owner requirement, 2026-10-29)

Two levels of use:

1. **Single instances**: the owner opens the orchestrator of one project (on the Mac or on the dev server alf_ubuntu) and works inside it, as today.
2. **A common control point** ("control tower") across all projects and machines, from which the owner can:
   - see the state: projects, tasks by state and by machine/session that has them in charge, running executors (screen sessions, worktrees, elapsed time, cost), pending questions from executors, deliveries waiting for verification, failures;
   - send a message to a specific orchestrator instance or executor session (steer, answer a question, ask for status);
   - act: stop/cancel a run, reassign a task to another machine/session, trigger verification.

## Constraints / context

- Depends on the common project registry (N079) as its data source, plus per-project task trees and run/event logs.
- Must work across machines (Mac + alf_ubuntu over ssh); instances may be Claude Code or Kilo sessions; executors run in GNU screen inside git worktrees.
- Deterministic state (registry, task states, runs, events) is owned by code; LLM sessions are invoked on events (delivered -> verifier, question -> answerer), not kept alive to poll.
- Reuse what exists (ai-orchestration-ui dashboard, broker, sessions, events, questions, triggers) rather than adding a parallel mechanism; please state which parts already cover this.

## Related

N078 (upgrade path for consuming projects), N079 (common registry of projects across machines).

## Clarification from the owner (2026-10-29)

The control tower is multi-machine by definition: from the Mac the owner wants the panel of the other server (alf_ubuntu) too, i.e. one view and one place to send messages, check state and act on orchestrator instances and executors running on any of his machines. A per-host dashboard (e.g. ai-orch-ui on each machine, port 8780 in BOOTSTRAP_ALF_UBUNTU.md) is not enough on its own; it must aggregate hosts (over ssh tunnels or a per-host agent the Mac panel talks to). See N081 for the multi-host gaps.

## Attach to an executor session from the panel (owner, 2026-10-29)

"If we can, I open the screen from that interface": from the control tower the owner wants to open the live terminal of a running executor/orchestrator session on any host, e.g. an embedded web terminal (xterm.js over a websocket) that runs `ssh <host> -t screen -x <session>` (shared attach: the agent keeps running, detach without stopping it). Optionally a read-only mode for watching.

Constraints: this is a real shell on the target host, so the endpoint must be reachable only locally/through the ssh tunnel, authenticated, never exposed publicly; session names must be resolvable from run/session records (standard naming such as `agent-<task>` per host), which requires the screen/tmux run backend asked in N081.
