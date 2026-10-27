# Spec — Orchestrator role per project, with workspace fallback

> **Status:** Draft v1 (2026-10-28) by ai-coding-tools-87 (orchestrator of ai-orchestration, ai-swissknife), to be
> reviewed by ai-coding-tools-58 (orchestrator of git-code-rag) and by Codex.
> **Owner decision (2026-10-28, note N074):** "gli orchestrator sono per progetto": there is an orchestrator role **per
> project**; a project without its own orchestrator is handled by the **workspace orchestrator** (fallback).
> **Builds on:** `orchestrator-control-plane-study.md` (T073: authority matrix, pull-only mailbox, liveness dimensions,
> transactional succession) — this spec changes the KEY of the role, not those rules. Supersedes "one orchestrator per
> workspace" in `events-and-triggers.md` §0 and `orchestration-broker-mcp.md` (mail address).
> **Absorbs/relates:** T079 (workspace resolution from a subdirectory), T083 (provider id is the identity), T071
> (registration hint), 16.7/16.8 (broker workers, mail). N068 is already fixed by T070 (done 2026-10-27).

## 0. Why

2026-10-27/28, workspace ai-coding-tools: two legitimate orchestrators (87 for ai-orchestration + ai-swissknife, 58
for git-code-rag) could not both be registered: the single workspace role was taken by 58 (gen 4) and handed back
(gen 5). UI, mail and handoff could show only one of them.

## 1. Role key and resolution

- A role is keyed by `(workspace_uuid, project_id)`. `project_id = _workspace` is the workspace role.
- **Who orchestrates project P** (resolution, used by UI, routing, CLI): P's own holder if P has one and it is not
  `released`; otherwise the `_workspace` holder (fallback); otherwise none (shown as "no orchestrator").
  A holder of P is never overridden by the workspace holder, whatever its liveness: liveness affects display and
  takeover eligibility (§4), not resolution. (Agreed with 58's point 1.)
- **Workspace role scope:** `_workspace` tasks, inbox triage of the workspace registry, cross-project coordination
  (workspace tasks with cross-project refs), and fallback for projects without a holder. It does not dispatch into a
  project that has its own holder; it may send that holder mail.
- A session may hold roles in several projects (87 holds ai-orchestration and ai-swissknife). Each key has its own
  generation, cursor, queue and handoff state; fencing is per key.

## 2. Data model and migration

- Storage: the current per-workspace `orchestrator.json` (+ sessions registry) gains per-project entries:
  `roles[<project_id>] = {generation, current, cursor, queue, pending_handoff?}`; sessions keep `(tool,
  provider_session_id)` as identity (T083) and list the keys they hold.
- **Migration (one-time, preview/apply):** the existing workspace role becomes `roles["_workspace"]` with its
  generation, cursor and queue unchanged. The current holder may then declare the projects it actually orchestrates
  (`sessions register --role orchestrator --project P ...`), which creates those keys at generation 1. Single-project
  workspaces are unchanged in practice (their only project resolves to the `_workspace` holder until a project holder
  registers).
- Events record the key they concern (`project` is already on task events; add it on role events).

## 3. CLI

- `--project P` (repeatable, or comma list) on `sessions register --role orchestrator`, `orchestrator status|reassign|
  hand-off|rotate|queue|enqueue|accept-handoff`. Default project when omitted: the project resolved from the current
  directory (T079: nearest registered project, else the workspace) — and the command prints which key it used. A role
  command never applies to "the whole workspace" implicitly: `_workspace` is an explicit key.
- `orchestrator status` without `--project`: one line per key (project, holder, tool, kind, liveness fields per T073
  Q-G, generation) plus, for each project without a holder, `-> falls back to _workspace (<holder>)`.
- `sessions role --project P`, `orchestrator status --project P --json` for tools/UI.

## 4. Authority, liveness, takeover (T073 rules applied per key)

- **Claim** a key with no holder: a self-identifying session (provider id) or the owner.
- **Hand-off**: the current holder (voluntary) or the owner; toward an interactive session it creates a
  `pending_handoff` that the target accepts explicitly (`orchestrator accept-handoff --project P`).
- **Takeover of a live holder: NOT by an agent with `--force`** (differs from 58's point 6; T073 Q-F, Codex blocker,
  and the 2026-10-28 mis-takeover is exactly the case). An agent that wants a role held by a live session sends it a
  handoff request (mail, §5) and the owner or holder decides. The owner may reassign an active role (authenticated
  owner action, T073 Q-F). A stale holder (`takeover_eligible`, T073 Q-G) may be taken over by the owner, or by any
  session after the holder declared expiry.
- **Liveness:** heartbeat older than N minutes (configurable per workspace, default 120 for interactive, 10 for
  headless) makes `heartbeat_valid=false`; fallback does NOT change (resolution §1), only display and
  `takeover_eligible`. Interactive Claude Code sessions do not heartbeat by themselves (T071): the skill tells them to
  heartbeat at each turn/check-in; until they do, they show `heartbeat_valid=false` without losing the role.

## 5. Routing (events, mail, triggers)

- Task/question/use-case/inbox events of project P go to the resolved orchestrator of P (§1); events of `_workspace`
  to the workspace holder. Mail address `workspace:P` reaches P's resolved holder; `workspace` reaches `_workspace`.
- Delivery to interactive holders is pull-only (mailbox read on the next turn + UI/OS notification), never prompt
  injection (T073 Q-E). Headless holders: one broker/trigger worker per key that has a headless holder (16.7 adapts to
  per-key workers).

## 6. UI and VS Code

- Project view: the project's orchestrator (holder, tool, kind, liveness) or "falls back to <workspace holder>".
- Workspace view / fleet panel (T073): all keys with holders and which projects fall back; actions per key (request
  handoff, accept handoff, owner reassign) following T073's authority matrix.

## 7. Acceptance

1. Two sessions hold different projects of one workspace at the same time; `orchestrator status` lists both; neither
   bumps the other's generation.
2. A project without a holder resolves to the `_workspace` holder; registering a project holder changes the resolution;
   releasing it falls back again.
3. Migration keeps the workspace role's generation/cursor/queue under `_workspace`; preview shows exactly that.
4. From a project subdirectory, commands default to that project's key and say so (T079).
5. An agent cannot take a live holder's key; a handoff request reaches the holder's mailbox; the owner can reassign.
6. Events of P are routed to P's resolved holder; mail to `workspace:P` likewise.
7. Real case: ai-coding-tools with 87 on ai-orchestration + ai-swissknife and 58 on git-code-rag, `_workspace` held by
   87; claude-mcp falls back to 87.

## 8. Plan (initiative 18, ordered; sizes S/M)

18.P1 key model + migration (`_workspace`) + status listing (M) · 18.P2 `--project` on register/status/reassign/
hand-off/rotate/queue with cwd default (needs T079) (M) · 18.P3 resolution function + routing of events/mail (M) ·
18.P4 authority per key: claim, handoff request/accept, owner reassign, no agent takeover of a live holder (M) ·
18.P5 liveness per key and takeover eligibility (S) · 18.P6 UI/VS Code project and workspace views (M) ·
18.P7 skills/AGENTS.md: register per project, heartbeat (with T071) (S). These merge into initiative 18 of T073
(18.1..18.8) before it is planned in detail.

## 9. Open points for the owner

- Whether the `_workspace` holder may also dispatch into a project whose holder is stale (not released) when the
  owner is away. Recommendation: no automatic dispatch; it mails the project holder and shows the project as
  "holder stale" in the UI; the owner decides.
