# N090 Cross-session review 2026-10-31: defects, missing capabilities and sweep scripts for ai-orchestration

- id: N090
- title: Cross-session review 2026-10-31: defects, missing capabilities and sweep scripts for ai-orchestration
- kind: feature
- status: ready
- created: 2026-10-31T14:33:57.160630+00:00
- author: gcube-audit-0b (gcube_audit coordinator, Claude)
- about: N088, N089, kilo-mcp, initiative 16, initiative 19, UC035
- produced: -
- processed-by: -
- short: Cross-session lessons

# Lessons from the cross-session review of 2026-10-31

Input for ai-orchestration. Complements N088 (transport: live registry, campaigns, decision register) and N089 (six working rules).
Scope reviewed, 2026-10-21 to 10-31: about 86 Claude Code sessions (Mac and hub, 16 workspaces plus tooling workspaces), 524 Kilo
root sessions (482 Mac, 42 hub), the kilo-mcp task store (788 completed, 131 failed, 49 cancelled, 3 stale `running`), 29 Kilo
worktrees on the Mac and several on the hub. Counts are from read-only sweeps (scripts in `scripts/`), not from opinions.

Component names used below: **TP** = task-pipeline skill and `tasks/AGENTS.md` convention; **ENG** = `tasks_engine` / `ai-orch` CLI;
**SESS** = sessions registry; **BRK** = broker MCP (initiative 16); **HUB** = hub registry and console (initiative 19); **KMCP** =
kilo-mcp server and queue; **CONTRIB** = `contrib/` hub scripts; **HL** = headless Claude runs; **AGM** = AGENTS.md pattern and the
orchestration-workflow skill. "NEW" means no existing task or note found for it in `tasks/00-INDEX.md` (verify before filing).

## A. Defects

**D1. kilo-mcp tasks stuck `running` with dead pids.** Symptom: 3 tasks `running` since 2026-10-30 17:55-18:00 (a queued feedback
round over three workspaces), processes gone. Root cause: no reconciliation of `running` records against pid liveness at server
start or on `kilo_task_status`/`wait`. Component: KMCP. Related: NEW. Fix: on every status read and at start, mark a `running` task
whose pid is dead and whose log shows no activity as `lost` (distinct from `failed`), and keep its branch/worktree pointer.
Acceptance: kill -9 a running task; within one poll `kilo_task_status` returns `lost`, and `kilomcp_tasks.py` lists no stale `running`.

**D2. Stale queue lock.** Symptom: `queue-runner.lock` pointed at a defunct pid on 2026-10-31 while queued tasks were not draining.
Root cause: lock acquired without liveness/age check on take-over. Component: KMCP. Related: NEW (same area as D1). Fix: lock holds
pid + start time + host; a contender steals it when the pid is dead or the start time differs. Acceptance: a test that leaves a lock
with a dead pid, starts the runner, and sees the queue drain.

**D3. Mass failure of queued tasks.** Symptom: 6 tasks failed together at 2026-10-30 18:29 (3 in one workspace, 1 a design study in
ai-orchestration itself); one was never redone. Root cause: not established (a common event: runner or server restart, or provider
error). Component: KMCP + BRK. Related: NEW. Fix: failures sharing a timestamp window are grouped as one incident with a cause field
(restart, provider, quota, lock) and offered for requeue in one action; `NOT_RETRIED` list from `kilomcp_tasks.py` becomes a CLI view.
Acceptance: after a simulated runner restart, tasks interrupted by it are tagged `interrupted:restart` and requeueable together.

**D4. `failed` / `completed` status is unreliable.** Symptom: of 131 `failed` records most are runs whose log ends with the normal
"finished, result read from the run log" line; 131 rows carry `unknown` backfilled on 2026-10-21 05:33. Telemetry and
`kilo_task_wait` are wrong for exactly the sessions that need collection. Root cause: status derived by log parsing after the process
has exited, with no exit code or terminal marker. Component: KMCP. Related: NEW. Fix: record exit code, last Kilo finish reason, and
whether commits exist on the branch; classify `completed` / `completed-no-commit` / `failed(reason)` / `cancelled(by)`.
Acceptance: replay of the 2026-10-21..31 store reclassifies the clean-finish records; `kilo_metrics` failure rate drops accordingly.

**D5. Runs ended mid-run are invisible.** Symptom: 46 of 482 Mac Kilo root sessions ended with a last part still `tool:running` or
`step-finish:tool-calls`; many are cancels after the commit, so a raw count misleads; the ones that matter have a worktree left on
disk. Root cause: no link between session end state and worktree/branch state. Component: KMCP + ENG (sweep). Related: UC035, spec
executor-housekeeping-and-completion. Fix: sweep joins end state, worktree and "is the session id referenced anywhere" (220 of 482
were). Acceptance: `ai-orch sweep kilo` prints only runs with unmerged work or no collector, with the reason.

**D6. Headless Claude permission rule wrong.** Symptom: 11 headless runs of a feedback round could not write their reply
(2026-10-30); 9 replies recovered from stdout logs, 2 runs relaunched. Root cause: the allow rule was written as `Write(path)`
where the tool needed `Edit(path)`; no preflight. Component: HL. Related: N088 R3 (capability profile). Fix: a launcher that builds
the allow list from a declared profile (`read-only+reply-path`) and runs a dry write check before the real prompt. Acceptance: a
headless run started with a deliberately wrong rule fails in the preflight, not after the work.

**D7. Session names change on restart; messages to dead sockets are lost silently.** Symptom: a session was addressed by a name that
no longer existed after restart; a message arrived as the receiving session died (network error) and was never processed; requests
waited for answers that never came (counts in section C). Root cause: the cross-session channel addresses a mutable name and has no
delivery receipt. Component: SESS + BRK. Related: T083 (provider id identifies the session; rename updates the record), N088 R1/R3.
Fix: stable session id in addressing; send returns `delivered` / `undeliverable`; undeliverable messages fall back to a mailbox note.
Acceptance: restart a session, send to its old name, receive either delivery to the new instance or a visible `undeliverable`.

**D8. Duplicate delivery after a session limit.** Symptom: a relay hit the 5-hour limit before delivering; the same text was
delivered later by two other relays (2026-10-31 13:38 vs 14:27). Root cause: no idempotency key on messages. Component: BRK. Related:
NEW. Fix: message id + dedup at the receiver. Acceptance: sending the same message id twice yields one inbox note.

**D9. Hub delivery script error leaves partial broadcast.** Symptom: a broadcast reached 8 Mac inboxes and failed on the hub with a
script error; recall meant deleting 8 files by hand, and the assistant safety check blocked variable-based `rm`. Component: CONTRIB
+ BRK. Related: N088 R2 (hold/recall). Fix: delivery is transactional per campaign (all recipients recorded before any write; recall
is a command). Acceptance: induced failure on one host leaves a `partial` campaign that `recall` clears without manual deletion.

## B. Missing capabilities

**M1. Sweep of leftovers.** Need: one command listing what delegation left behind. Data the tool must produce (observed 2026-10-31):
29 Kilo worktrees behind Mac sessions: 15 with commits not merged into the default branch, 11 of those with no remote ref, 14 merged
and idle; one worktree with 11 dirty files and 12 commits ahead whose session ended mid-run and appears in no transcript; hub: 3 + 1
unmerged Kilo branches in one repository, 13 + 1 stale in a second clone, 5 worktrees in one porting workspace, 8 unmerged branches in
a service workspace; 3 stuck kilo-mcp tasks; 2 backup directories left from a move; about a dozen workspaces with an untracked
feedback folder after one round. Component: ENG + HUB. Related: UC035 (cleanup), spec executor-housekeeping-and-completion, T082
(`kilo_cleanup`, `kilo_verify_worktree` patterns). Fix: `ai-orch sweep [worktrees|kilo|kilo-mcp|pending]` (scripts provided) with
JSON output so the console can render it; never deletes. Acceptance: on a prepared fixture with 3 unmerged worktrees, 1 merged, 1
stuck task, the output lists exactly those; with `--json` it validates against a schema.

**M2. Delegation closure.** Need: a delegation record that stays open until the delegator reads the result and the branch is merged,
pushed or deleted. Observed: delivered subtasks of two initiatives (a dozen-plus tasks each) merged and never verified; delivered
results of 4 Kilo branches waiting for a live orchestrator that had not said it would collect them; 5 branches of one library
pushed nowhere. Component: TP + ENG + AGM. Related: UC006/UC017/UC037 (verification), N089 rule 4. Fix: a `delegation` event in the
ledger (run id, task id, branch, delegator session) closed by `ai-orch task verify|bounce|drop`; `tasks verify-pending` lists open
ones by age. Acceptance: a task in `delivered` for more than N days appears in the sweep with its delegator.

**M3. Agent run registry (subagents).** Need: record of subagent launches and their hand-backs. Observed: the parent transcript only
shows the launch acknowledgement; completion could not be told in most cases, so "delegated, never checked" cannot be measured for
subagents. Component: SESS + ENG. Related: NEW. Fix: each launch writes id, parent session, purpose; each hand-back or stop updates
it. Acceptance: the sweep reports subagents launched without a hand-back.

**M4. Acknowledgement of inbox notes.** Need: sender can see whether a note was received and processed. Observed: about 18
cross-session requests dropped and 21 owner questions never answered in the gCube workspaces alone. Component: TP + BRK. Related: N089
rule 2, spec inbox-notes. Fix: note states `delivered` -> `acknowledged` (moved to `integrated/` with a task id) -> `answered`; the
sender's `ai-orch inbox outstanding` lists notes older than a threshold. Acceptance: a note not moved within the threshold shows in
the sender's list.

**M5. Canonical-copy awareness (Mac / hub).** Need: a workspace id resolves to the canonical host and path; writes to the other copy
are refused or warned. Observed: notes written to the non-canonical copy; two writable copies of ai-orchestration itself on the hub
(authoritative one for executors, owner clone with 12 stale feature branches and a long-lived integration branch holding 33 patches
not in main); the Mac and the hub holding different tips of the same feature branch; two workspaces existing as Mac and hub copies
with no remote; unpublished commits on the Mac in 3 repositories after the move to the hub. Component: HUB + BRK + SESS. Related: N088
R5, initiative 19, T073. Fix: registry field `canonical: {host, path, since}`; `ai-orch doctor` flags divergent tips and
non-canonical writes. Acceptance: two copies with different tips of the same branch are reported with both commit ids.

**M6. Session-limit awareness.** Need: remaining budget as a planning input and an automatic "write in-flight state" step. Observed:
4 sessions hit the 5-hour limit at 2026-10-31 13:36 with agents or Kilo runs in flight; an orchestrator stopped on a limit on
2026-10-26 leaving a delegated initiative without a collector; an onboarding session died on the weekly limit on 2026-10-28 with an
unanswered question. Component: AGM + SESS + HL. Related: NEW. Fix: sessions registry stores limit state when reported; before a
long delegation the skill requires a check; a session-end hook (or the next session's first sweep) writes Progress to the task.
Acceptance: a session near the limit produces a Progress entry in every task it had `in progress`.

**M7. Broadcast validity.** Need: broadcasts and campaigns carry a release condition and an expiry. Observed: a "stay blocked"
broadcast of 2026-10-30 20:03 remained effective about an hour after its blocker closed. Component: BRK + TP. Related: N088 R2
(release condition), N089 rule 6. Fix: broadcast notes have `valid-until: task:<id> closed | date`; receivers and the console treat
expired ones as informational; repeating one requires re-evaluation. Acceptance: closing the named task marks the broadcast released
in every recipient view.

**M8. Capability declaration of recipients.** Need: senders know before asking whether a recipient can write to a host or run
headless. Observed: one session could not write on the hub and asked that nobody do it in its place; the sender found out only after
asking. Component: SESS + HUB. Related: N088 R6. Fix: capabilities in the registry; request routing refuses or reroutes to the
decision owner. Acceptance: a request needing hub-write to a session without it is rejected at send time.

**M9. Workspace discovery.** Observed: a registry listing 6 entries when 16 workspaces existed; discovery done by hand across
transcript dirs, `.kilo` dirs, agent lists and ssh. Component: ENG + HUB. Related: N088 R1, Q026/Q028 (discovery, answered but not
committed at review time). Fix: `ai-orch workspace discover` using the scripts' inventory as a candidate source, always requiring
confirmation before registering. Acceptance: unregistered workspaces with sessions in the last N days are listed as candidates.

**M10. Machine-readable owner decision source.** Observed: owner decisions reached sessions relayed by peers and could not be
told from an agent asserting one. Component: BRK + HUB. Related: N088 R4. Fix: decisions cite register ids. Acceptance: a task
header field `decision: D-nn` is validated against the register.

## C. Process gaps

**P1. Projects without a registry.** 4 workspaces (a knowledge base, a catalogue tool, a chat-agent service, a research workspace)
had no `tasks/00-INDEX.md`; their pending work lived only in transcripts. Component: TP + ENG (`tasks init`, UC038 drift detection).
Related: N089 rule 1, UC030. Fix: `ai-orch doctor` lists registered workspaces with sessions and no registry, and offers `tasks init`.
Acceptance: the four are reported; after init the sweep sees their open items.

**P2. Decisions only in transcripts or untracked files.** 8 decisions in the gCube workspaces plus more in two others existed only
in a session; rules and host state files cited by every session sat untracked in two hub clones; one session offered to write a wait
note and did not; an owner action requested in one session stayed untracked in every task file. Component: TP + AGM. Related: N089
rules 1-2. Fix: end-of-turn check in the AGENTS.md block ("anything decided or requested this turn is a task, a question or an inbox
note") plus a sweep list of untracked files under `status/`, `_inbox/`, `tasks/`. Acceptance: `ai-orch doctor` reports untracked
files in task-tree paths per workspace.

**P3. Several writers on one artefact.** One shared configuration repository was changed from 3 workspaces in separate merge
requests; ai-orchestration itself had 2 writable copies. Component: AGM + HUB. Related: N089 rule 3, spec orchestrator-role-per-project,
Q032. Fix: registry field `owner-of: [paths or repos]`; a doctor check for second writable clones; requests to the owner via inbox.
Acceptance: opening a second writable clone of a registered repo triggers a warning naming the owner workspace.

**P4. Delivered work not verified.** Same data as M2; the process gap is that "delivered" has no clock and no named verifier.
Component: TP. Related: UC006, UC037. Fix: `delivered` carries `verify-by` and a verifier; stale ones escalate in the console.
Acceptance: see M2.

**P5. Unanswered owner questions and orphan roles.** 21 owner questions never answered; curator role unclear between two sessions of
one workspace; a retired orchestrator whose role moved twice. Component: TP + HUB. Related: spec orchestrator-role-per-project, T073.
Fix: questions listed in the console by age; role handoff is a registry event. Acceptance: open questions older than a threshold
appear in `ai-orch sweep pending`.

**P6. Host-level work tracked in an unrelated project.** A host hardening item lived in a task of an unrelated personal workspace.
Component: TP. Related: NEW. Fix: doctor warns on tasks whose subject is a registered host record but whose workspace is not the
host's. Acceptance: the item is flagged for re-homing. (Generic; no content of the item is carried here.)

**P7. Feedback folders left in many workspaces.** About a dozen workspaces kept an untracked feedback folder after a round. Component:
BRK (campaigns). Related: N088 R2. Fix: campaigns own a cleanup step; replies are collected then removed or committed.
Acceptance: after a campaign closes, no untracked campaign folder remains.

## D. Priority suggestion

Immediate (small, high value): D1, D2, D4, D6, then M1 (scripts already exist). Next: M4/M5/M7 with N088/N089 design.
Larger: M2/M3/M6 need ledger events and a runs registry; fold into initiative 16 and 19 planning.

---
- Author: gcube-audit-0b (gcube_audit coordinator, Claude)
- Workspace: /Users/Alfredo/works/gcube_audit
- ai-orch: 1.1.0 (2965604)
- Date: 2026-10-31 14:33:56 UTC
