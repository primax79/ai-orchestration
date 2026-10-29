# Review — multi-machine-development-architecture.md (draft 1)

- **Date:** 2026-10-29
- **Reviewed:** `tasks/specs/multi-machine-development-architecture.md` draft 1, with source notes N078-N083.
- **Method:** the claims were checked against the code (`scripts/`, `tasks_engine.py`, `orchestration_config.py`, `bin/ai-orch`, `ai-orchestration-ui`, `kilo-mcp`), against the related specs and recorded owner answers (Q001-Q031), and against the Kilo CLI source (`kilocode-dev` 7.4.20; installed CLI 7.8.8, where only the help output was compared). Three independent reviews: Claude (synthesis and code checks), Codex, and Gemini (`gemini-4-argon` via kilo-mcp). Findings that reviewers reached separately are marked **[3/3]** or **[2/3]**.
- **Verdict:** the direction is sound and the owner decisions hold. The spec cannot become an initiative as written. Its central mechanism (claim = push) does not fit the task engine, the run engine or the event system. It reopens settled decisions without saying so. Its security section leaves the console and `kilo serve` open to local agents. Most of this goes away if the hub decision is applied fully (§1).

## 1. Main recommendation: take "hub, not peers" to its conclusion

The spec chooses a hub but keeps peer features: executors on the Mac, takeover between machines, and git push as the arbiter between hosts. Those features cause most of the blockers below.

**Proposal for v1: all engine mutations and all runs happen on the hub.** The Mac is a client. It works through `ssh hub ai-orch …`, the console, its own clones (git push of hand-written specs and notes), and optionally IDE sessions that call the hub's CLI/MCP over ssh.

What this buys:

- **Claims:** the existing host-local `flock` + `--expect-task-hash` on the hub is already a correct compare-and-swap (`tasks_engine.py:1308-1350`, `:2565`). No git CAS is needed in v1.
- **Run start and claim:** `ai-orch run start` already does `open → in progress` (`orchestration_runs.py:5070-5100`). That is the claim. You only add `host` to it.
- **Events:** events keep being emitted inside the locked mutation on the one host that has the triggers (B3 disappears).
- **Liveness:** `reconcile()` stays correct, because every run is local to the host that reads it (B2 shrinks).
- **Roles and fencing:** they stay in the hub's `.ai-orchestration/`, with no cross-host role handover. This matches N081 decision 1.

What remains to build for multi-machine use:

- host identity;
- the hub engine committing and pushing its own task mutations to the bare repo (today no engine commits; see B1);
- the console;
- the screen backend;
- the security of §15.

Executors on the Mac and cross-host takeover become v2, designed once v1 is stable.

## 2. Blockers

### B1 — The claim protocol does not fit the engines [3/3]

- **The CAS is on the whole branch, not on the task.** A rejected push means "the branch moved", not "T205 is taken". Claims, inbox notes, questions and handoffs all contend on one ref. One retry is not enough under normal traffic.
- **The command sequence is wrong after contention.** Once the loser has committed locally, `git pull --ff-only` fails. It has to fetch, inspect `origin`, and drop or rebase its own commit.
- **No engine commits.** `tasks_engine` and the run supervisor change `tasks/` in the working tree under a local `flock`, and do not commit (`orchestration_runs.py:5070-5100`). The supervisor even writes `in progress` uncommitted in the main checkout. "A claim is a commit" is a new layer that races with these automatic transitions.
- **A claim blocks the run.** `run start` refuses `execute` on a task already `in progress` unless it continues an existing run (`orchestration_runs.py:1518`). A task claimed by §6.2 can never be started with `ai-orch run start`.
- **Releasing has no legal transition.** There is no `in progress → open`. The legal path is `in progress → paused → open` (`task-and-state-model.md` §3), and the spec does not mention it.
- **Delivery has two owners and causes conflicts.**
  - §9 has the executor write `delivered` on its own branch. `agent-runs-from-ui.md` R6 makes `run mark-delivered` the only path to `delivered`, and the generic transition refuses it.
  - The claim fields (committed on main) and `delivered` (committed on the branch) edit the same header lines, so merges conflict.
  - The index merge driver covers only `00-INDEX.md`, not task headers.

If git CAS is still wanted in v2, use **one ref per task**, for example `refs/ai-orch/claims/T205`, created with `git push --force-with-lease=refs/ai-orch/claims/T205: …`. An empty expected value means "must not exist", which is a real CAS per task with no contention on `main`. The engine then copies the claim into the header. Either way, define the single transaction **claim → run → delivered → release**, with one owner per step.

### B2 — Takeover by lease plus "no visible run" allows split-brain [3/3]

"Old claim + collector sees no run" (§6.2) gives wrong answers when ssh is down, the collector has crashed, the Mac is asleep or a clock is wrong. The old executor keeps pushing while the new one starts.

The spec also contradicts decisions already recorded:

- T073 Q-D: process and file probes are display hints and never authorize a takeover.
- **Q028 is still open on exactly this point.**
- Q025=B: automatic takeover only by a configured headless standby.

Fix:

- v1: no automatic takeover. The owner forces it.
- Every takeover increments a per-task generation, carried by the run and checked when it delivers.
- Today `reconcile()` would mark another host's run `lost` and **try to kill its pgid** (`orchestration_runs.py:2879-2930`). It needs a host check before runs can ever be shared or synced.

### B3 — Events do not travel with `git pull` [found by the specs review only]

Events are emitted inside the locked CLI mutation, with a per-workspace `seq` (`events-and-triggers.md` §1, E1). A change that arrives by `git pull` emits nothing. Rules such as `verify-on-delivery` would never fire on the hub for work delivered elsewhere. Each host also has its own `seq`, while I18 §2.4 bases the cutover watermark on `event_seq`.

The proposal in §1 avoids this. Otherwise you need a reconciler that runs after each pull, compares headers and synthesizes events.

### B4 — Role key and role model conflict with Initiative 18 and T073 [3/3]

- **Key:** §7/§10 use the key `(project, role)`. I18 uses `(workspace_uuid, project_uuid | "_workspace")`, with the uuid as identity, per-key fencing and a cutover watermark. Adopt I18's key and add a role dimension, `(workspace_uuid, project_uuid | "_workspace", role)`; do not create a second model.
- **Multiple roles per session:** "one session may hold several roles" is not supported. `role`/`role_id` in the session record are scalars (`orchestration_sessions.py:501`), and I18 treats multiple holdings as a v2 migration.
- **Authority:** the interlocutor has no entry in T073's authority matrix (Q031=A). Should it be allowed to edit task headers? Today only a category's owner-session edits its tasks, and `outside_project_role_scope` applies (I18 §1.5).
- **Product code:** "never product code" contradicts Q013=A of the contextual chat (T074), and the spec does not cite T074.

### B5 — The console and `kilo serve` are open to local agents [3/3]

- **Console token:**
  - The UI token sits in the `<meta>` of `index.html` and in `~/.config/ai-orchestration/ui-token`.
  - Any agent that can reach the tunnel can read it.
  - Q031=A requires a human-bound confirmation (`osascript` or a VS Code modal), which cannot run on a headless hub. The confirmation has to happen on the client.
- **Web terminal:**
  - A `ttyd` session running `ssh -t <host> screen -x` is a shell on every host. It bypasses every preview → hash → confirm gate.
  - Its "read-only" mode is not a security boundary unless it is enforced below the terminal process.
  - The UI's CSP has `frame-ancestors 'none'`.
  - The Host allowlist accepts only `127.0.0.1`/`localhost` on the UI's own port, so a tunnel on another local port is refused unless `AI_ORCH_ALLOWED_HOSTS` is set.
- **`kilo serve` without a password:**
  - It listens on `127.0.0.1:4096` with no authentication unless `KILO_SERVER_PASSWORD` is set (`cli/cmd/serve.ts:15`).
  - On a hub with several users, any local process can post prompts to it, which means it can run code as the `kilo` user.
  - The password must be required, kept in a file readable only by its own user, and passed through the environment, never through argv. kilo-mcp reads it with `ps eww`, which will not work across users.
- **Screen across users:**
  - If agents run as the `kilo` user, the owner cannot run `screen -x` on their sessions without screen multiuser mode and ACLs.
  - Multiuser mode needs a setuid screen, which Ubuntu does not install by default.
  - Alternatives are `ssh kilo@hub screen -x …` with a dedicated key, or tmux with a shared socket and group permissions. Pick one.
- **Separation of credentials (Codex):** the console needs its own account. Each host needs a restricted ssh key with a command allowlist. The console must resolve host and session names itself and never put user text into the shell. Every action needs an audit record, `owner (via console@host)`, as in Q024.

## 3. Executor model: §7 and §8 mix two runtimes

The Kilo source shows that with `kilo run --attach` **the agent loop runs inside the `kilo serve` process**. The process in screen is only a thin client. This has four consequences.

1. **`screen -x` on an executor shows the client's output, not the agent.** The owner's interactive path is `kilo attach <url> -s <id>` (TUI) or the VS Code extension.
2. **If `kilo serve` restarts, every running turn stops** (`serve.ts:29-53`). The sessions persist in `kilo.db` and can be resumed, but the work in progress is lost. A single systemd unit becomes a single point of failure for every executor. Standalone screen + `kilo run` processes are isolated from each other.
3. **A message sent mid-turn is queued, not rejected.** It cuts the current turn short at the next step boundary, with reason `superseded` (`session/prompt.ts:1425-1449`, `1868-1876`). So "send a message to the executor" redirects it rather than informing it. In addition, the `run` client stops when the session goes idle and may miss work started by later messages. That breaks the deterministic tracking the spec relies on.
4. **Headless runs deny the `question` tool** (`run.ts:467-493`). Non-blocking questions need their own channel in any case.

**The owner has not confirmed this executor model** (N083). It is a separate decision with clear trade-offs. Suggestion for v1: standalone `kilo run` in screen, plus fork-to-ask (`kilo run -s <id> --fork`) for status checks, which already worked on T205. Try `--attach` only after measuring items 2 and 3.

**`kilo remote` (OQ6) is ruled out.** It streams messages, diffs and state to `wss://ingest.kilosessions.ai` and needs a Kilo login (`kilo-sessions.ts:424-484`, `:635-647`). That violates the non-goal "no public interface", and it would send private projects to a third-party cloud.

## 4. Factually wrong or incomplete statements in the spec

| § | Statement | Reality | Evidence |
| --- | --- | --- | --- |
| 7 | roles are `roles/<role>.json` | the orchestrator is in `.ai-orchestration/orchestrator.json`; the other roles are in `roles/<role>.json` | `orchestration_sessions.py:301-416` |
| 7 | a session holds several roles | scalar role; multiple holdings are v2 in I18 | `orchestration_sessions.py:501` |
| 10 | handoff "builds on" existing material | the handoff is a generated prompt in `.ai-orchestration/orchestrator/turns/` (git-excluded), not a document; rotation only on `rotate_after_tokens` | `orchestration_orchestrator.py:1197`, `:1974-1980`, `:285-290` |
| 17 | code reads only `.ai-orchestration.local.toml` or the global path | true for `orchestration_config` and triggers. `tasks_engine` also reads `tasks/orchestration.toml`, `<proj>/orchestration.toml` and `tasks/AGENTS.md`. The rendered AGENTS.md is correct (and a test enforces it). The wrong docs are `docs/00-QUICKSTART-AND-PLAYBOOK.md:117-149`, `orchestration-setup/SKILL.md:68,138` and `orchestration-config-and-agents-md.md` §3. The fix is to **unify the lookup**, not only the docs | `tasks_engine.py:425`, `:596-685`; `orchestration_config.py:341-358` |
| 18 | Upgrade: "none" | `ai-orch tasks upgrade` exists (preview, `--apply --expect-plan-hash`, `--migrate-plans`, merge driver), and so does `env` doctor with ack/unack. Build on them | `tasks_engine.py:27257`; `orchestration_env.py:410-500` |
| 18 | Preflight: only assistant CLIs | true for `env status`. However `[project.verification_checks]` already exists; it is only rendered into AGENTS.md, never run | `orchestration_config.py:1367-1380` |
| 6.2 | new fields via `extension_fields` "validated" | only the field names are validated; values are free text. Microtask headers are a closed set, and plan tasks `NN.T` have no header | `tasks_engine.py:12010-12016`, `:12332-12349` |
| 6.2 | `run-ref` | duplicates `run-id`; the `run_id` regex has no host part | `task-and-state-model.md` §2.2 |
| 8 | kilo-mcp uses `.kilo/worktrees/<task>` | it uses `.kilo/worktrees/<flattened branch name>` | `kilo-mcp/server.py:5957-5970` |
| 8 | `ai-orch run` uses `../.worktrees/<repo>/<run_id>` | true for `start`, but `run preview` reports `run-<task_id>`/`verify-<task_id>` (separate bug) | `orchestration_runs.py:4789` vs `:4133`, `:3542` |
| 9 | question with `blocks: none`, executor carries on | the grammar is `blocks: -`. Run agents never call `questions ask`; their questions come only from the final message and are forced to block (blocking-questions §4, Q8). The "finish on an assumption" mechanism already exists: `conditions:` (Q12/Q13) | `orchestration_runs.py:1165-1180`, `:1265-1270` |
| 9 | messages are durable records "in git or run dir" | the broker spec puts mail in per-host SQLite, and mail to an unattended orchestrator is quarantined until the owner accepts it (broker §6). The main interlocutor → orchestrator channel would be quarantined every time | `orchestration-broker-mcp.md` §2, §6 |
| 18 | "converge on one run store" with kilo-mcp | agent-runs §2 and I18 18.4d decided to keep them separate (tag, do not merge). Reopening this needs a stated reason | — |

## 5. Overlaps and decisions dropped without comment

- **Interlocutor:** it overlaps with the session `role: console` (events-and-triggers §0a, broker §5). Neither is cited.
- **Handoff document `tasks/handoff/<role>-<project>.md`:** it duplicates T073's `pending_handoff` + `handoffs/gen-<N>.md` and I18's `roles/<K>/handoffs/`, and drops the pull-only `accept-handoff` step. The incoming session's "summary as acknowledgement" proves only that it read the document (Codex). Use generation + source commit + event cursor + hash, and an append-only acceptance record.
- **Web console (phase 3):** it duplicates the `Workspaces Fleet` tab (I18 18.7-18.8, Q029=A).
- **Dropped from T073/I18:** the four liveness dimensions, the cutover watermark, durable parking, project aliases, the schema v2 migration, `verify-by` routing, and `in_flight_runs` (18.4d).
- **Specs not cited:** `contextual-element-chat.md` (T074), `owner-interactions-study.md` (T076), and `task-and-state-model.md`, which is the one most affected.
- **Initiative 18 is not in `00-INDEX.md`.** The new phases would overlap with 18.x and with the 16.7/16.8 sequencing.
- **Archive tags:** `archive/<branch>` contradicts the cleanup rules in executor-housekeeping §3 and in `run cleanup`.
- **Versioned config vs local config:** preflight and the port registry are "versioned in config". orchestration-config §2 says agent config is local and never committed. Also, the rendered AGENTS.md (in git) contains a per-host absolute config path, which differs between the Mac and the hub.
- **Registry:** workspaces are identified by `canonical_path`, `device` and `inode` (`orchestration_registry.py:245-280`), so the table cannot be shared across hosts. The hub registry needs a portable identity (uuid) plus per-host paths.

## 6. Scope: what to defer and what is missing

**Defer:** the collector daemon (use stateless `ssh <host> ai-orch … --json` instead), automatic credit-aware reassignment (manual switch plus classification of 429/quota errors), automatic handoff triggers other than context threshold and manual, the embedded web terminal, automatic project discovery, Mac executors and cross-host takeover.

**Missing for the phase 1 exit criterion** ("a day of work from the CLI console"):

- the claim → run → delivered → release transaction (B1);
- the hub engine committing and pushing to the bare repo;
- the policy for when the Mac is offline;
- tests for push contention;
- hub recovery (restore and promotion of the Gitea mirror; at least the RPO).

## 7. Proposed order

| Slice | Content | Why first |
| --- | --- | --- |
| 0 | ricerca_auto hygiene (T202, T209) **plus** `doctor`/`upgrade` built on `tasks upgrade` and `env` doctor; unify the config lookup | N078 is what actually caused the problems seen on 2026-10-29; low cost, immediate value |
| 1 | host identity (`host` in `run.json` and task headers); host-aware `reconcile()` (never mark or kill another host's run); screen backend with standard names and an exit status file; executable project preflight (from `verification_checks`) with timeouts; `ai-orch console status` and `attach` over ssh; `kilo serve` password if used | hub-only v1, no distributed protocol |
| 2 | the hub engine commits and pushes its own transitions; the delivered/release transaction; `describe run` | single master in practice |
| 3 | per-project roles reconciled with I18 + role dimension; interlocutor in the T073 authority matrix; pull-only mailbox (16.7/16.8) with a non-quarantined channel from the interlocutor; handoff based on T073's `pending_handoff`; global skill for IDE sessions | after deciding Q026/Q028 |
| 4 | web console = the I18 Fleet tab extended to several hosts; actions with confirmation on the client; terminal only after B5 | — |
| v2 | Mac executors, git CAS through per-task refs, takeover with generation | only if v1 shows a need |

## 8. Proposed answers to the open questions

- **OQ1:** queue on the hub with immutable message ids and a per-session read cursor. An offline client keeps running work it has already been granted (fenced work), but cannot take new claims or roles.
- **OQ2:** no automatic takeover in v1; the owner forces it and the generation is incremented. In v2, a renewable lease with a heartbeat; time alone never authorizes a takeover. The decision belongs to Q028.
- **OQ3:** keep `../.worktrees/<repo>/<run_id>` (agent-runs §5.4: neutral with respect to the provider, and outside the repo, so watchers and indexers are not slowed). Leave kilo-mcp alone (18.4d). Fix the `run preview` bug.
- **OQ4:** a persistent logical role, with physical sessions that rotate. Continuity comes from the handoff document plus the event cursor, not from the provider's transcript.
- **OQ5:** a manual switch (`provider drain <tool>`) plus classification of auth, quota and 429 errors from run streams. Balance APIs are hints at most.
- **OQ6:** ssh tunnels (`ControlMaster` + `LocalForward`). `kilo remote` is ruled out (§3).
- **OQ7:** I18's key plus the role dimension. The interlocutor in the authority matrix may triage, create notes and tasks, and answer questions addressed to the owner when delegated. It may not run code, cancel runs, reassign tasks or take over without the owner.

## 9. Decisions only the owner can take

1. ~~**Hub-only v1** vs Mac executors from the start.~~ **Decided 2026-10-29: Mac executors from the start** (see §10).
2. ~~**Executor model.**~~ **Delegated to the reviewer, decided 2026-10-29:** standalone `kilo run` in screen (see §10.4).
3. ~~**Owner of `delivered`.**~~ **Decided 2026-10-29: the executor**, with the hub acknowledging it (see §10.5).
4. **Q026 and Q028** (still open, blocking T073): they determine the takeover rules.
5. ~~**Attaching to agents that run as a separate user.**~~ **Decided 2026-10-29 by the reviewer (minor decision):** `ssh kilo@hub -t screen -x <name>` (see §10.6).
6. **Interlocutor and product code:** "never" (this spec) vs Q013=A (contextual chat may edit code).

## 10. Owner decision (2026-10-29) and the revised design

**Decision:** executors must also run on the Mac in v1. **Constraint stated by the owner:** project work must not slow down if the system fails or turns out to be inadequate.

This replaces "all runs on the hub" from §1 with **one writer of task state (the hub), runs on any host**. The things §1 bought are kept. The hub's `flock` + hash remains the compare-and-swap. Events are still emitted on one host, and there is still no git CAS.

### 10.1 Run on a client (the Mac)

1. **Claim:** `ai-orch run start <T> --host mac` on the Mac first runs the claim on the hub: `ssh hub ai-orch tasks claim <T> --host mac --run <run_id> --expect-task-hash <h>`.
   - On the hub it is the normal `open → in progress` transition, under the hub's `flock`. It also records `host` and a **per-task generation**.
   - The hub engine commits and pushes to the bare repo, and emits the event on the hub.
2. **Run on the Mac:** the Mac pulls, creates the worktree (`../.worktrees/<repo>/<run_id>`) and starts the executor in screen. `run.json` carries `host: mac` and the generation.
3. **Liveness by push, not by poll:** the Mac supervisor sends a heartbeat to the hub (`ssh hub ai-orch run heartbeat <run_id> …`), with state, last log line, cost and exit status.
   - The hub never has to reach a laptop that is behind NAT or asleep.
   - The console reads everything on the hub.
   - `screen -x` on Mac sessions is only available from the Mac itself, or through a reverse tunnel when you want it.
4. **Delivery:** the executor commits on its branch, and the supervisor pushes the branch to the bare repo. Then it calls `ssh hub ai-orch run mark-delivered <run_id> --generation <g>`.
   - R6 is kept: `delivered` is written only by `mark-delivered`, on the hub.
   - The hub refuses a stale generation.
   - The `run.delivered` event fires on the hub, so `verify-on-delivery` works.
5. **`reconcile()` on any host** only acts on runs where `host == this host`. For the others it shows the last heartbeat and its age, and never marks or kills them.
6. **Takeover:** owner only (`--force-takeover`), which increments the generation. If the old run reconnects, its delivery is refused (fencing).

### 10.2 "Do not slow down" guarantees (requirements, not options)

- **Degraded mode when the hub is unreachable:** `run start --offline` on the Mac claims locally. It writes `host: mac` and `claim: offline` in the header, commits locally and starts the run straight away.
  - When the hub comes back, a reconcile step pushes the claim. If the hub has meanwhile given the task to someone else, it stops and asks the owner; it never resolves the conflict on its own.
  - With a single owner such a collision is rare, and when it happens it is visible.
- **No hard dependency:**
  - Today's workflow keeps working on every project: screen + `kilo run` by hand, kilo-mcp, Claude sessions in the IDE.
  - Multi-host is opt-in per project (`[multi_host] enabled = true`).
  - Turning it off must not require a migration back: the new fields are additive and ignored when the feature is off.
- **Every slice useful on its own and removable:**
  - No slice ships without a fallback.
  - The console is a view, never the only way to act.
  - If something breaks, the owner goes back to plain `ssh` + `screen -x` + git with no data lost.
- **Developed outside the projects:** the tool is developed and tested on a test project before it goes onto ricerca_auto. A project adopts a slice only after a "day of real work" on the test project has gone without incidents.

### 10.3 Revised order

| Slice | Content | Value even if the later slices never ship |
| --- | --- | --- |
| 0 | ricerca_auto hygiene; `doctor`/`upgrade` built on `tasks upgrade`; unified config lookup | projects aligned, drift visible |
| 1 | host identity (`host` in `run.json` and task headers); `reconcile()` that ignores other hosts' runs; screen backend; executable preflight + timeouts | local runs on either machine are safe and standardized |
| 2 | `tasks claim` and `run mark-delivered` called remotely on the hub; heartbeat; generation/fencing; offline mode with reconcile; `console status` on the hub | Mac and hub executors on the same queue, no double claims |
| 3 | roles (I18 + role dimension), interlocutor, mailbox, handoff | after Q026/Q028 |
| 4 | web console on the I18 Fleet tab | — |

### 10.4 Executor model: standalone `kilo run` in screen

- **Isolation:** each executor is its own process. Restarting or crashing a shared `kilo serve` does not kill every run (§3, point 2).
- **Determinism:** the process exit means the run is over. The supervisor's tracking does not depend on idle detection, which a follow-up message can make wrong (§3, point 3).
- **Same on the Mac and the hub:** no server per host, no password to manage, no discovery through `ps`/`lsof`. It is the mechanism that already worked on T205.
- **Status questions:** `kilo run -s <id> --fork --agent ask` reads the session without touching the run.
- **Steering:** cancel, then continue the same session with corrective instructions (the `continue_session_id` pattern of kilo-mcp). Or, for non-urgent messages, a mailbox read at the start of the next turn.
- **`--attach` stays an opt-in experiment** behind a flag. It is adopted only if a measurement shows that being able to open the live session interactively is worth the single point of failure.

### 10.5 `delivered` is declared by the executor and acknowledged by the hub

The executor knows when it has finished: commits made, self-check and Final Report done. So the executor declares delivery. The two problems found in B1 are solved by ordering, not by moving the responsibility:

1. **Claim before the worktree.** The claim (state, `host`, generation) is committed and pushed to main *before* the worktree is created. The branch therefore starts from a header that already contains it.
2. **The executor writes `state: delivered` in its branch**, in the same commit as its Final Report or right after it.
3. **The supervisor pushes the branch and calls `ai-orch run ack-delivery <run_id> --generation <g>` on the hub.** This replaces `mark-delivered`. The hub reads the header from the pushed branch and checks:
   - the generation;
   - that commits exist after the base;
   - that the state is `delivered` and the Final Report is present.
   It then writes the same line on main and emits `run.delivered`.
4. **No conflict at merge:** main and the branch carry identical changes on the header lines. The rare case where main changed the same header meanwhile (for example the owner paused the task) is a real conflict, and it goes to the owner.
5. **If the executor did not declare `delivered`** (crash, timeout, a run left half done), the hub does not invent it. The task stays `in progress`, the run is `failed`, and the failure path follows.

R6 of `agent-runs-from-ui.md` changes from "only `mark-delivered` writes `delivered`" to "the executor declares it, and only the hub's acknowledgement makes it count on main". This also aligns with `executor-housekeeping-and-completion.md` §5.

### 10.6 Attaching to agents that run as the `kilo` user on the hub

- **Why it is needed:** screen sockets are per user (`/run/screen/S-kilo/`). The owner's own account does not see the `kilo` user's sessions.
- **Chosen:** a dedicated ssh key for `kilo@hub`. The console and the owner run `ssh kilo@hub -t screen -x <name>`. Access to `kilo` gives no extra power, because the user has no Docker, no sudo and no production secrets.
- **Ruled out:** multiuser screen (needs setuid) and tmux with a group socket (more permissions to maintain).
- **On the Mac:** executors run as the owner's own user. The separate user exists only on the hub, where the production secrets are.

Decisions 4 and 6 in §9 are still open.
