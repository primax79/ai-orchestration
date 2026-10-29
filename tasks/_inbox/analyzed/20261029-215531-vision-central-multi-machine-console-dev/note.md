# N082 Vision: central multi-machine console, development in screen sessions, VS Code optional

- id: N082
- title: Vision: central multi-machine console, development in screen sessions, VS Code optional
- kind: idea
- status: processed
- created: 2026-10-29T21:55:31.547530+00:00
- author: owner (via claude, ricerca_auto architect session)
- about: N078; N079; N080; N081
- produced: specs/multi-machine-development-architecture.md (+ review 2026-10-29), initiative 19, UC038-UC040, T087
- processed-by: claude (ai-coding-tools session, 2026-10-29)

## Vision (owner, 2026-10-29)

"My idea is to move towards a centralized console from which I manage and interact with all developments. VS Code becomes an optional tool for when I want to interact with the code, but development happens directly in the sessions in screen."

## What it implies

- **Primary interface = a central console** across all projects and all machines (Mac, alf_ubuntu, future hosts): state of every project/task/run, messages to and from orchestrator instances and executors, questions to answer, deliveries to verify, decisions to take, and live attach to any session's terminal (N080).
- **Where work happens = long-lived agent sessions in GNU screen** (or tmux) on the machine that owns the task, each in its own git worktree, with standard names, logs and status; local orchestrators per machine/project drive them (N081).
- **VS Code is optional**, used to read/edit code by hand; nothing in the workflow may depend on an IDE extension being open (today parts of the flow assume VS Code: Kilo extension sessions, IDE-hosted Claude sessions).
- **Projects onboard and stay aligned automatically** (N078) and are listed in one registry shared by the machines (N079).

## Request

Treat this as the product direction for ai-orchestration: a spec/initiative "central multi-machine console" that orders N078-N081 into a roadmap (registry and host identity first, screen run backend and claims next, console with attach last), and check existing specs (orchestrator-control-plane-study T073, broker, peer-messaging, agent-runs-from-ui, ai-orchestration-ui) against it, since several declare remote/multi-machine a non-goal.

## Decisions and model refined with the owner (2026-10-29)

**Principle:** use what exists, build what is missing (kilo serve / run --attach / remote for sessions and messaging; a ready-made web terminal such as ttyd for screen attach; ai-orchestration-ui as console base; git for durable state; ai-orch sessions/roles/rotation/handoff). Build only the glue.

**Hub:** alf_ubuntu is the center, the Mac a client (see N081).

**Three roles per project, assignable to different sessions or held by the same one:**
1. **Interlocutor** — the owner's interactive interface to the project (one per project, reachable from the console as a chat): answers about state, code, history and decisions; turns owner requests into inbox notes/tasks/answers; messages the orchestrator. Reads everything, does not implement. Persistent session with rotation.
2. **Orchestrator** — deterministic engine (queue, dependencies, dispatch, wait, events) plus short LLM turns for judgement. **Provider: Kilo** (gemini-3.8-flash) by default.
3. **Executor** — headless, attached to `kilo serve` (`kilo run --attach`) so the engine tracks it deterministically while the owner can open the same session or message it via API; mailbox only as fallback for executors without attach (e.g. `claude -p`).
A fourth, short-lived **verifier** role must differ from the executor (cross-agent).

**Provider constraints:** Claude credits are limited. Orchestration and mechanical work go to Kilo; Claude is used for judgement (independent verification, spec review). The **interlocutor must be interchangeable between Kilo and Claude**, and roles must be reassignable when a provider runs low (credit-aware fallback: Claude -> Kilo gemini-4-argon -> Codex for verification).

**Automatic periodic handoffs (required):** session memory lives in a provider-neutral handoff document in git (project state, open threads with the owner, pending decisions, recent requests and where they went), never only in a session context. The engine triggers the handoff on: context size threshold, elapsed time / end of day, provider credits below threshold, any change of provider or machine. The outgoing session writes it; the incoming one (any provider) acknowledges with a short summary kept in the log, so a bad handoff is visible immediately. Build on the existing ai-orch rotation/handoff prompt, which is the one already-portable piece.

## IDE sessions as first-class participants (owner, 2026-10-29)

The owner must be able to open a VS Code session (Kilo or Claude) in any workspace, and that session must know, from **global skills/configuration** (not per-project hand-written instructions), how to interact with the agents underneath:
- discover on start: who holds which role (interlocutor, orchestrator), which tasks are claimed by whom and on which host, which executors are running;
- interact: message the orchestrator/interlocutor, read an executor's state or attach to its session, claim a task with the git flow (pull, header, commit, push; rejected push = already claimed), never touch tasks/files claimed by others, register itself as a session with a role (e.g. "owner-assisted development");
- mechanism: `ai-orch` CLI and `ai-orch mcp` (broker tools) as the interface both Kilo and Claude can use; one global skill ("working in an ai-orchestration-managed workspace") auto-loaded when the workspace is registered, distributed by the existing plugins (architect-side/shared) to `~/.claude/skills` and Kilo's global skills; the rendered AGENTS.md adds project specifics.
- skills and global config must be the **same version on every machine** (Mac and alf_ubuntu): the tool-side counterpart of N078 (drift detection and upgrade apply to installed skills/config too).
