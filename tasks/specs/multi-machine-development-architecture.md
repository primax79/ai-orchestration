# Spec — Multi-machine development architecture: hub server, central console, role-based sessions in screen

- **Status:** draft 1 (2026-10-29), written from a working session on `ricerca_auto` with the owner. **Reviewed 2026-10-29** (Claude, Codex, Gemini): [`multi-machine-development-architecture.review-2026-10-29.md`](multi-machine-development-architecture.review-2026-10-29.md). **Where this spec and the review's §10 differ, §10 wins** (hub = single writer of task state with runs on any host, Mac executors in v1, standalone `kilo run` in screen, `delivered` declared by the executor and acknowledged by the hub, owner-only takeover, no `kilo remote`).
- **Drives:** [`19-multi-machine-development`](../19-multi-machine-development/plan.md).
- **Sources:** inbox notes `N078` (upgrade path), `N079` (common registry), `N080` (control tower and screen attach), `N081` (multi-host gaps and owner decisions), `N082` (vision, roles, providers, handoffs, IDE sessions).
- **Related specs (to reconcile, not replace):** `orchestrator-control-plane-study.md` (T073), `orchestrator-role-per-project.md` (Initiative 18), `orchestration-broker-mcp.md`, `ui-multi-project.md` (16.9), `peer-messaging.md`, `agent-runs-from-ui.md`, `executor-housekeeping-and-completion.md`, `blocking-questions.md`, `events-and-triggers.md`, `control-plane-safety.md`, `orchestration-config-and-agents-md.md`.
- **Reference project:** `/Users/Alfredo/works/ricerca_auto` (tasks T201-T209 there; T205 is the first task run on the hub).
- **Language of the owner:** Italian; this spec is in English as the repository's specs are.

---

## 1. Summary

The owner develops on more than one machine and wants to move from "an IDE session per project" to **a central console from which he manages and talks to every development on every machine**. Development happens in **long-lived agent sessions running in GNU screen** on the machine that owns the task; VS Code becomes an optional tool for hands-on code.

Decisions already taken by the owner (2026-10-29):

1. **Hub, not peers.** One always-on machine (today `alf_ubuntu`) is the center; the Mac and future machines are clients.
2. **Durable state stays in git, with a single master.** Task files are already the shared state; the only problem was two writable masters. One bare reference repository per project on the hub; claiming a task is a commit whose push may be rejected (compare-and-swap).
3. **Live state is per host** (runs, screen sessions, processes, logs) and is collected by the console from each host.
4. **Three roles per project** (interlocutor, orchestrator, executor) plus a short-lived verifier; roles are assignable, several may be held by the same session.
5. **Orchestrator on Kilo; Claude credits are limited**; the interlocutor is interchangeable between Kilo and Claude.
6. **Automatic periodic handoffs** in a provider-neutral document.
7. **IDE sessions are first-class participants** that learn the mechanism from global skills/configuration.
8. **Use what exists, build what is missing.**

ai-orchestration today is single-host by design (remote/multi-machine is an explicit non-goal in `orchestration-broker-mcp.md` §8, `peer-messaging.md` §9, `agent-runs-from-ui.md` §10). This spec defines the target architecture and the delta.

## 2. Context and evidence (2026-10-29)

Observed on `ricerca_auto` while moving its development to `alf_ubuntu`:

- **Two writable masters.** The Mac repo and the server repo push to each other (`receive.denyCurrentBranch=updateInstead`), producing cross merges (`Merge alf_ubuntu/master: ...`); no copy exists outside the two machines.
- **Ad-hoc execution.** Executors launched by hand as `screen -dmS <name> bash -lc 'kilo run --auto ... | tee .tmp/<x>.log'`, prompt in a file, worktree in `.kilo/worktrees/<task>`; long-lived dev servers also in screen; the architect (Claude on the Mac) drives everything through ssh (quoting errors, `compose exec`/`kilo run` swallowing the heredoc stdin, `~` expanded on the wrong side, 120 s tool timeouts).
- **No way to talk to a running headless executor**: to ask T205's Kilo run about its status the session had to be forked (`kilo run -s <id> --fork --agent ask`).
- **Executor feedback** (from that fork): worktree isolation and the Goal/Non-goals/Steps/Verification spec format work well; the task was too large for one commit; there is no asynchronous channel to raise an issue without stopping; the target environment was not checked before dispatch (`bun` missing on the server); 120 s command timeouts are too short for a 717-test suite.
- **Project drift**: `ricerca_auto` had not been aligned with ai-orchestration since 2026-10-17 (no config, not registered, index without generated markers, AGENTS.md duplicated, `tasks validate` 38 errors) — `N078`.
- **Credits**: one Claude session acted as interlocutor and orchestrator and spent credits on mechanical work (waiting, polling over ssh).
- **Host security mattered** for the design: agents run with `--auto` as a user in the `docker` group (root-equivalent) and able to read production secrets; Docker-published ports bypass `ufw`.

## 3. Goals and non-goals

### Goals

- G1. One central console (CLI first, then web) showing all projects on all machines, with messaging, actions and live terminal attach.
- G2. Any machine can run orchestrators and executors; every task records which host has it in charge; work can be taken over from another machine.
- G3. One reference repository per project and an off-site mirror; no peer-to-peer pushes into checked-out branches.
- G4. Role-based sessions (interlocutor, orchestrator, executor, verifier) with provider-neutral state and automatic handoffs.
- G5. Sessions opened ad hoc in an IDE (Kilo or Claude) discover and respect the mechanism through global skills and the `ai-orch` CLI/MCP.
- G6. Projects are onboarded and kept aligned automatically; tools and skills are the same version on every machine.
- G7. Credit-aware provider policy: mechanical work never consumes scarce providers.

### Non-goals (for this spec)

- Multi-user access (other people operating the console). Single owner, several machines.
- Running the console or any agent endpoint on a public interface.
- Replacing git as the durable store with a database or a consensus service.
- Building our own terminal emulator, agent runtime or chat protocol when an existing one fits.

## 4. Principles

1. **Use what exists, build what is missing** (owner). Existing pieces: `kilo serve` / `kilo run --attach` / `kilo remote`, Claude Code session messaging and remote control, GNU screen, a ready-made web terminal (e.g. `ttyd`) for `screen -x`, `ai-orchestration-ui`, `ai-orch` sessions/roles/rotation/handoff, questions, inbox, events, triggers, git.
2. **Scripts first, LLM only for judgement.** Scheduling, waiting, liveness, retries and bookkeeping are code; LLM turns are short and event-triggered (delivered → verify, question → answer, ready → refine spec).
3. **Durable state in git, live state on the host that owns it.**
4. **Provider-neutral memory.** No role's continuity may live only inside one provider's context window.
5. **Never inject text into a live interactive session** (inherited from T073): messages reach interactive sessions through a pull-only mailbox read on their next turn, plus a notification to the owner. Owner-typed input via terminal attach is the only direct path.
6. **The console is a view and a remote control, never a dependency**: if it is down, sessions keep running and can be reached with plain `ssh` + `screen -x`.
7. **Least privilege on the hub**: agents do not get root-equivalent rights or production secrets.

## 5. Topology

```text
                 owner
                   │ browser / terminal
                   ▼
   Mac (client) ── ssh tunnels ──► alf_ubuntu (hub, always on)
   - console UI in browser          - bare repos ~/git/<project>.git (single master)
   - optional IDE sessions          - registry, broker, console backend (127.0.0.1)
   - optional executors             - per-project orchestrator + interlocutor (screen)
     (register to the hub)          - executors in screen + git worktrees
                                    - dev services as systemd --user units
                                    └─► off-site mirror (owner's private Gitea)
```

- **Hub**: hosts the reference repositories, the registry (N079), the broker and the console backend, all bound to `127.0.0.1` and reached by the Mac through ssh `LocalForward`.
- **Clients**: the Mac (and future machines) clone from the hub, open the console in a browser through the tunnel, may run executors locally; a client-side executor appears in the console through a per-host collector (§11) reached by the hub over ssh, or not at all if the client is offline (its tasks show as claimed by that host).
- **Port registry** (per hub, versioned in the global config): every service and executor port is allocated from one table. Real collision observed: `ai-orch-ui` is documented on 8780 (`BOOTSTRAP_ALF_UBUNTU.md`) while `ricerca_auto`'s production Caddy uses `127.0.0.1:8780`. Proposed ranges for `ricerca_auto` on the hub: 8765 dev backend, 5173 dev frontend, 8766-8779 executor live checks (one per task), 8743/8780 production via tunnel; console and broker get their own reserved range.

## 6. Repositories and durable state

### 6.1 Single master

- One bare repository per project on the hub: `~/git/<project>.git`. Every working copy (hub, Mac) has it as `origin`. Pushing into checked-out branches (`updateInstead`) is retired.
- Off-site mirror: push-mirror from the hub to the owner's private Gitea after every push (hook or timer). Repositories the owner marked "never push" (e.g. private security audits) use an encrypted bundle instead.
- Merged executor branches are archived as tags `archive/<branch>` before deletion; produced work is never discarded.

### 6.2 Claiming a task (git as arbiter)

```text
git pull --ff-only
edit header: state: in progress, host: <host>, claimed-by: <session>, claimed-at: <iso>
git commit -m "tasks: claim T205 on alf_ubuntu"
git push            # rejected non-fast-forward => someone else moved first:
                    #   pull, re-read the header, pick another task
```

- `ai-orch tasks claim <id> --host <h> --session <s>` wraps the sequence and retries the pull-check once.
- Release: same flow with `state` change and `host` cleared or moved. Takeover from another machine: allowed when the claim is older than a lease and the claiming host's live state shows no run (§11), or when the owner forces it.
- New header fields, added first through `[tasks] extension_fields` (no code change), then promoted to the core schema: `host`, `claimed-by`, `claimed-at`, `run-ref` (host-qualified run id). The free-text convention seen in `ricerca_auto` (`executor: kilo (alf_ubuntu)`) is replaced by these validated fields.
- Questions (`tasks/questions/Q###`), inbox notes, handoff documents and decisions all live in git and travel with `pull`.

## 7. Roles

| Role | Purpose | Session type | Default provider | Writes |
| --- | --- | --- | --- | --- |
| **Interlocutor** | The owner's interactive interface to one project: answers about state, code, history, decisions; turns requests into inbox notes, tasks, answers to questions; messages the orchestrator. "If I talk to it, it becomes a task." | interactive, persistent, in screen; rotates with handoff | Kilo or Claude, interchangeable | inbox, task headers/specs, questions, handoff doc; never product code |
| **Orchestrator** | Queue, dependencies, dispatch, wait, collect, trigger verification, bookkeeping | deterministic engine + short LLM turns | Kilo (`gemini-3.8-flash`) | task states, run records, events |
| **Executor** | Implements one task in its own worktree | headless, attached to `kilo serve` (`kilo run --attach`) | Kilo; Claude/Codex when the spec says so | its branch only |
| **Verifier** | Independent check of a delivered task | short-lived | a provider/model different from the executor's | verdict, `bounced`/`verified` |

- Roles are records in `ai-orch sessions` (`roles/<role>.json`), extended with `host`. One session may hold several roles in a small project (e.g. interlocutor + orchestrator); the console shows holders per project.
- Executor session type: headless gives a certain end and deterministic tracking; attaching it to `kilo serve` keeps the owner able to open the same session interactively and send messages via the Kilo API (the mechanism kilo-mcp already uses for `kilo_respond_question`). To be validated in phase 1 (§15). Executors that cannot attach (e.g. `claude -p`) use the mailbox fallback.
- **IDE sessions** (owner opens VS Code with Kilo or Claude in a workspace) register as a session with a role such as `owner-assisted`, see claims and running executors, and follow the same claim and messaging rules (§12).

## 8. Runtime on each host

- **Run backend `screen`** for `ai-orch run`, next to the current setsid supervisor: session name `agent-<project>-<task>` (executors), `orch-<project>`, `talk-<project>` (interlocutor); log `.ai-orchestration/runs/<run_id>/session.log` (screen `-L`), status file written on exit (exit code, end time, final report pointer).
- **Worktrees**: one convention for every executor (today `ai-orch run` uses `../.worktrees/<repo>/<run_id>` while kilo-mcp and the hub use `.kilo/worktrees/<task>`): pick one, make the other an alias, record the path in `run.json` and the task header.
- **Liveness** is evaluated only on the host that owns the run (pid, screen session, status file); `reconcile()` must never mark a run of another host as `lost`.
- **Long-lived services** (dev backend/frontend, broker, console backend, collectors) run as `systemd --user` units (linger enabled) bound to `127.0.0.1`, not in screen.
- **Shared host resources** declared per project (dev database, production stack, ports): executors receive them in the prompt as forbidden or allocated resources.

## 9. Communication

| From → To | Channel | Blocking? |
| --- | --- | --- |
| Owner → interlocutor | console chat (or terminal attach) | no |
| Interlocutor → orchestrator | mailbox (pull-only, T073) + event | no |
| Orchestrator → executor | prompt at start; Kilo API message for attached executors; mailbox otherwise | no |
| Executor → orchestrator / owner (question) | non-blocking question record: `tasks/questions/` entry with `blocks: none` or a per-run `QUESTIONS.md` read by the orchestrator turn; the executor continues on a stated assumption | no |
| Executor → orchestrator (completion) | process exit + status file + `state: delivered` in its branch's task file | — |
| Owner → any session | terminal attach (`screen -x`) from the console | — |

- Agent-to-agent text is never injected into a live interactive session (§4.5).
- Every message is a durable record (git or run dir), so a handoff or a provider switch loses nothing.

## 10. Handoffs

- **Document**: `tasks/handoff/<role>-<project>.md` (git), provider-neutral, sections: project state; open threads with the owner; decisions pending; recent requests and where they went (note/task ids); running work (host, run, session names); next steps; known risks. Overwritten at each handoff, previous versions in git history.
- **Triggers (engine, not goodwill)**: context-size threshold (as today's rotation); elapsed time and end of day; provider credits below threshold; any change of provider or host; owner request from the console.
- **Protocol**: outgoing session writes the document and commits; incoming session (any provider) reads it and posts a short acknowledgement summary to the run log and the console; the owner sees a mismatch immediately. Builds on the existing fenced succession (generation, fencing token) for the role itself, now keyed by `(project, role)` and carried across hosts by the hub registry.

## 11. Live state collection

- A small **per-host collector** (stdlib Python, `systemd --user`, read-only) exposes on `127.0.0.1` the host's live state: screen sessions, runs and their status files, worktrees, Kilo sessions (`kilo session list` per worktree), resource usage, toolchain preflight results.
- The hub console backend queries collectors over ssh tunnels (or runs the collector command over ssh); clients that are offline appear as such.

## 12. Console

- **Phase 1 — CLI** (`ai-orch console …`): `status --all-hosts` (projects, tasks by state and host, runs, questions waiting, deliveries to verify), `attach <task|session>` (`ssh -t <host> screen -x <name>`), `say <project> <text>` (to the interlocutor's mailbox), `claim`/`release`/`move <task> --host`.
- **Phase 2 — web** on the hub (base: `ai-orchestration-ui`), opened from the Mac through the tunnel: per-project view with the interlocutor chat, task board with host column, run list with live log, questions and deliveries queues, actions (cancel run, reassign task, trigger verification, force handoff), **embedded terminal attach** (ready-made web terminal running `ssh <host> -t screen -x <session>`, read-only mode available).
- **Security**: the console is a remote shell on every machine: bound to `127.0.0.1` on the hub, reachable only through ssh tunnels, authenticated with a token that agents cannot read (T073 already flags that `~/.config/ai-orchestration/ui-token` is readable by local agents: owner-only actions need human-bound confirmation).

## 13. Global skills and IDE sessions

- One global skill, e.g. `working-in-an-orchestrated-workspace`, distributed by the existing plugins (`architect-side`, `shared`) into `~/.claude/skills` and Kilo's global skills on every machine: how to discover roles/claims/runs (`ai-orch` CLI and `ai-orch mcp`), how to claim, how to message, what never to touch.
- The rendered project `AGENTS.md` adds project specifics (shared resources, ports, verification commands).
- Skills and global config carry a version; `ai-orch doctor` (N078) reports drift on each machine and `ai-orch upgrade` aligns them.

## 14. Provider and credit policy

- Defaults: orchestrator Kilo `gemini-3.8-flash`; executors Kilo `gemini-3.8-flash` unless the spec requires otherwise; verifier different from the executor (Claude preferred for judgement); interlocutor Kilo or Claude.
- Credit awareness: the engine tracks provider availability/credit signals and, below a threshold, reassigns roles through a handoff (Claude → Kilo `gemini-4-argon` → Codex for verification; Claude ↔ Kilo for the interlocutor).
- Mechanical work (waiting, polling, routine checks) never runs in a Claude turn.

## 15. Security model on the hub

- Agents run as a dedicated user (`kilo`), not in the `docker` group, without sudo, without read access to production secrets; the owner's user keeps Docker and production.
- Docker-published ports are filtered in `DOCKER-USER` (they bypass `ufw`); everything agent- or console-related binds to `127.0.0.1`.
- Prompt-injection stance: untrusted text (scraped data, user feedback, other agents' outputs) never becomes instructions; mailbox messages are data for the receiving session's judgement.

## 16. Environment preflight

- Before dispatching to a host, the orchestrator runs the project's declared preflight on that host (tools and versions: e.g. `bun`, `node`, project venv; free ports; required services up; disk) and either fixes it (if allowed) or blocks the dispatch with a clear reason. Declared in project config next to `verification_checks`. Real case: T205 dispatched to a hub without `bun`.
- Per-project command timeouts for long suites are part of the same config (the executor reported 120 s as too short for 717 tests).

## 17. Onboarding and upgrade (N078, N079)

- Common project registry on the hub: identity, paths per host, primary host, reference repo and mirror, convention/schema version, roles and holders; per-host SQLite becomes a cache. Absorbs the owner's existing `~/works/MIGRATION_REGISTRY.json`.
- `ai-orch doctor` (drift report) and `ai-orch upgrade` (preview, plan hash, `--apply --expect-hash`): register, write config, adopt index markers, re-render AGENTS.md without duplicated hand-written blocks, migrate task headers, install/align global skills; refuses while executor worktrees of the project are active, or runs in a mode that does not touch them.
- Fix the config-location inconsistency found on 2026-10-29: rendered AGENTS.md and QUICKSTART tell to edit `tasks/orchestration.toml`, the code reads `.ai-orchestration.local.toml` or `~/.config/ai-orchestration/projects/<dir>/orchestration.toml`.

## 18. Mapping to existing components

| Need | Exists | Action |
| --- | --- | --- |
| Durable task state, questions, inbox | `tasks_engine`, `questions`, `inbox`, index merge driver | reuse; add `host`/`claimed-*` fields and `tasks claim` |
| Role holders, rotation, fenced succession, handoff prompt | `orchestration_sessions.py`, `orchestration_orchestrator.py` | extend key to `(project, role)` + host; add interlocutor role; provider-neutral handoff doc |
| Runs | `orchestration_runs.py` (setsid supervisor, pid reconcile) | add screen backend, host field, host-local reconcile, unified worktree path |
| Kilo executor tracking | kilo-mcp (separate local store), `kilo serve`/`--attach` | converge on one run store; use `kilo serve` for attach and messages |
| Mailbox | planned 16.7/16.8, T073 pull-only decision | implement as specified, add non-blocking executor questions |
| Console | `ai-orchestration-ui` (per host), 16.9 multi-project | hub-hosted, multi-host aggregation, terminal attach |
| Registry | `orchestration_registry.py` (per host SQLite) | hub registry, per-host cache |
| Preflight | `env status` checks assistant CLIs only | project toolchain preflight per host |
| Upgrade | none | `doctor` + `upgrade` |

## 19. Phased plan

| Phase | Content | Exit criterion |
| --- | --- | --- |
| 0 — Hygiene (project side, already tracked in `ricerca_auto` T202, T209) | hub firewall and `DOCKER-USER`, user `kilo`, bare repo + Gitea mirror, standard session names, one launch script, project aligned with ai-orch | `ricerca_auto` passes `tasks validate`; no peer pushes |
| 1 — Fields and CLI console | `host`/`claimed-*` via extension fields; `tasks claim`; screen run backend; per-host collector; `ai-orch console status/attach/say`; preflight; validate executors on `kilo serve --attach` | owner runs a day of `ricerca_auto` work from the CLI console |
| 2 — Roles and handoffs | interlocutor role; handoff document and automatic triggers; credit-aware reassignment; global skill for IDE sessions; `doctor`/`upgrade` | provider switch of the interlocutor without loss; IDE session respects claims |
| 3 — Web console | hub-hosted UI with multi-host aggregation, chat with interlocutor, embedded terminal attach, actions | owner manages all projects from the browser on the Mac |

Phases 1-3 run in ai-orchestration in parallel with the projects (owner: tool development does not slow project work); the stability requirement for consuming projects is covered by `doctor`/`upgrade`.

## 20. Open questions

- OQ1. Where the per-project roles and mailboxes live for a client-hosted session (Mac) when the Mac is offline: queue on the hub and deliver on reconnect?
- OQ2. Lease length for a claim and the rule for takeover without owner confirmation.
- OQ3. Worktree path convention to keep (`.kilo/worktrees/<task>` vs `../.worktrees/<repo>/<run_id>`).
- OQ4. Interlocutor persistence: one long-lived session with rotation (preferred) vs spawned per conversation from the handoff document.
- OQ5. How credit/availability signals are obtained per provider (API, error rates, manual switch).
- OQ6. Whether `kilo remote` (session relay) is preferable to tunnels for the console's access to Kilo sessions on the hub.
- OQ7. Reconciliation with `orchestrator-role-per-project.md` (role key `(workspace_uuid, project_uuid | "_workspace")`) and with T073's authority matrix for the new interlocutor role.
