# N083 Handoff: multi-machine development architecture spec, open the initiative and tasks

- id: N083
- title: Handoff: multi-machine development architecture spec, open the initiative and tasks
- kind: request
- status: processed
- created: 2026-10-29T22:08:55.490993+00:00
- author: claude (ricerca_auto architect session) for the owner
- about: specs/multi-machine-development-architecture.md; N078; N079; N080; N081; N082
- produced: specs/multi-machine-development-architecture.md (+ review 2026-10-29), initiative 19, UC038-UC040, T087
- processed-by: claude (ai-coding-tools session, 2026-10-29)

# Handoff to the ai-orchestration orchestrator: multi-machine development architecture

From: Claude, architect session of `ricerca_auto` (Mac), 2026-10-29. Owner instruction: "I need a formalization document; let him (the ai-orchestration orchestrator) open the tasks; you may annotate them, but finalizing and inserting is his job."

## What you receive

- **Formalization document:** `tasks/specs/multi-machine-development-architecture.md` (draft 1, not reviewed). Not yet in `00-INDEX.md` and no initiative/plan created: deliberately left to you.
- **Source notes:** `N078` upgrade path, `N079` common registry, `N080` control tower + screen attach, `N081` multi-host gaps + owner decisions, `N082` vision, roles, providers, handoffs, IDE sessions (all in `_inbox/to-analyze/`, 2026-10-29).
- **Evidence project:** `/Users/Alfredo/works/ricerca_auto` (Mac) and `alf_ubuntu:~/works/ricerca_auto` (hub). Relevant tasks there: T202 host hardening, T205 first executor run on the hub (Kilo in screen, worktree `.kilo/worktrees/t205`), T209 single reference repo on the hub with Gitea mirror.

## Owner decisions already taken (do not re-ask)

1. alf_ubuntu is the hub; the Mac and future machines are clients.
2. Durable state in git with a single master per project (bare repo on the hub); claim = commit + push, rejected push = already claimed.
3. Live state stays on each host and is collected by the console.
4. Roles per project: interlocutor (interactive, interchangeable Kilo/Claude), orchestrator (Kilo), executor (headless), verifier (different from executor). Roles assignable; one session may hold several.
5. Claude credits are limited: mechanical work never in Claude turns.
6. Automatic periodic handoffs, provider-neutral document in git.
7. IDE sessions learn the mechanism from global skills/config, same version on every machine.
8. Use what exists, build what is missing.
9. Backup of project repos: the owner's private Gitea.
10. Tool development runs in parallel with projects (it does not slow them); consuming-project stability via doctor/upgrade.

## Still open (spec §20 OQ1-OQ7) — need owner answers or your proposal

Offline client sessions, claim lease/takeover rule, worktree path convention, interlocutor persistence, credit signals per provider, `kilo remote` vs tunnels, reconciliation with `orchestrator-role-per-project.md` and the T073 authority matrix. Also: executor session type "headless attached to `kilo serve`" is a proposal the owner has not explicitly confirmed (he asked what "all interactive" meant, then moved on to roles).

## Please first

1. Review the spec against the related specs listed in its header (T073 study, Initiative 18, broker, 16.9, peer-messaging, agent-runs-from-ui): several declare multi-machine a non-goal and must be reconciled, not contradicted (e.g. T073's "never inject into interactive sessions" is adopted as §4.5).
2. Independent review (cross-agent) before turning it into an initiative.
3. Register the spec in the index and create the initiative/tasks your way.

## Suggested tasks (annotations only — finalize, split, rename or drop as you see fit)

Phase 1 — fields and CLI console
- A1. `host`, `claimed-by`, `claimed-at`, `run-ref` task fields (first via `extension_fields`), plus `ai-orch tasks claim|release|move` with push-as-CAS and one retry.
- A2. Run backend `screen` for `ai-orch run` (session names `agent-<project>-<task>`, `orch-<project>`, `talk-<project>`; `-L` log; exit status file), host field in `run.json`, host-local `reconcile()`.
- A3. Unify the worktree convention between `ai-orch run` and kilo-mcp (OQ3) and converge kilo-mcp's task store with the run store.
- A4. Per-host read-only collector (systemd --user, 127.0.0.1) exposing screen sessions, runs, worktrees, Kilo sessions, preflight.
- A5. `ai-orch console status --all-hosts | attach | say` (CLI console).
- A6. Project toolchain preflight per host before dispatch, plus per-project command timeouts.
- A7. Validate executors on `kilo serve` + `kilo run --attach` (attach and message a running executor via the Kilo API).
- A8. Port registry per hub in the global config (real collision: ai-orch-ui 8780 vs ricerca_auto Caddy 127.0.0.1:8780).

Phase 2 — roles, handoffs, alignment
- B1. Interlocutor role (sessions/roles), mailbox to orchestrator (16.7/16.8 as decided in T073), non-blocking executor questions.
- B2. Provider-neutral handoff document (`tasks/handoff/<role>-<project>.md`), engine triggers (context, time, credits, provider/host change, owner), acknowledgement summary.
- B3. Credit-aware role reassignment (Claude -> Kilo gemini-4-argon -> Codex for verification; Claude <-> Kilo for interlocutor).
- B4. Global skill "working in an orchestrated workspace" for Claude and Kilo, distributed by the plugins on every machine.
- B5. `ai-orch doctor` and `ai-orch upgrade` (N078), including skills/config drift per machine; fix the `tasks/orchestration.toml` vs `.ai-orchestration.local.toml` documentation inconsistency.
- B6. Hub registry of projects (N079), absorbing `~/works/MIGRATION_REGISTRY.json`.

Phase 3 — web console
- C1. Hub-hosted console based on ai-orchestration-ui with multi-host aggregation.
- C2. Interlocutor chat per project in the console.
- C3. Embedded terminal attach (ready-made web terminal over `ssh -t <host> screen -x`), read-only mode, token not readable by agents.
- C4. Console actions: cancel run, reassign/move task, trigger verification, force handoff.

Small fixes noticed on the way
- D1. `ai-orch describe` lists only part of the `run` subcommands.

## Not yours (stays in ricerca_auto)

Phase 0 hygiene for that project: host firewall and DOCKER-USER (T202), user `kilo` on the hub, bare repo + Gitea mirror (T209), aligning ricerca_auto with the current ai-orchestration conventions (task to be opened there after T205 ends).
