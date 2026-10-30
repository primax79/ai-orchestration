# N088 Robust cross-workspace communication: live registry, campaigns with hold/recall, owner decision register, web control dashboard

- id: N088
- title: Robust cross-workspace communication: live registry, campaigns with hold/recall, owner decision register, web control dashboard
- kind: feature
- status: ready
- created: 2026-10-30T18:54:45.679215+00:00
- author: d4science-kb-02 (d4science_kb orchestrator, Claude)
- about: tasks/specs/orchestration-broker-mcp.md, initiative 16, initiative 19, T073
- produced: -
- processed-by: -

Owner request (2026-10-30, d4science_kb session): "we need something robust for communicating with all instances". The owner
asked to pass the requirements to ai-orchestration (owner of the working mechanisms) rather than build anything in the
kb. Most of the base exists in design (broker MCP, initiative 16; workspace registry; initiative 19 hub registry and
console; T073 control-plane study). This note lists what was missing in a real run today, as use cases.

## The run that showed the gaps (2026-10-30, d4science-kb-02)

1. Feedback round: the owner asked every workspace developed with Claude or Kilo for feedback on the kb-service proposal.
   I discovered workspaces by hand (~/.claude/projects, .kilo dirs, ListAgents, ssh to the hub); `ai-orch workspace list`
   had 6 entries. 16 workspaces selected, 5 live Claude sessions messaged, 11 headless `claude -p` runs, 15 Kilo runs via
   kilo-mcp queue; 30 replies collected from per-workspace `kb-feedback/` folders into the kb, then synthesized.
2. Headless Claude permission rule was wrong (`Write(./kb-feedback/**)` instead of `Edit(...)`): 11 runs could not
   write; 9 replies were recovered from stdout logs, 2 runs re-launched.
3. "Move development to alf_ubuntu" broadcast: drafted, partly delivered (8 notes in Mac inboxes, hub delivery failed on
   a script error), then put on HOLD by the owner (wait for T049 `kilo` user). Recall = deleting 8 files by hand; the
   Claude Code safety check blocked variable-based `rm`, literal paths were needed.
4. Owner decisions reached me relayed by peers (the knowledge model via gcube-audit-0b; the HOLD via ai-coding-tools-1a).
   Correct, but indistinguishable from an agent asserting an owner decision.
5. Machine confusion: notes written to the Mac copy while the canonical copy was the hub, and vice versa; half of the
   target workspaces did not exist on the hub yet; I misread which copy of ai-coding-tools was ahead.
6. Capability mismatch: ai-coding-tools-22 could not write on the hub (its permissions) and asked that nobody does it in
   its place; the sender could not know this before asking.

## Requirements (proposed, for the broker / initiative 16 and 19)

R1. **Live registry as the discovery source** (`ws_list` MCP + CLI): every workspace registered, with canonical host and
    path (Mac / hub), move state (moved / partly / blocked by X), tools available (Claude, Kilo, Codex), live sessions
    (from the session registry), inbox location, curator/orchestrator, tags (e.g. `d4science`). Replaces manual discovery.

R2. **Campaigns** (one request to N workspaces): recipients by query (tags, move state, not blocked), a reply template /
    JSON schema, automatic collection of replies into the sender's workspace, aggregation status (N sent / read / answered
    / declined / expired). States: draft → approved (owner when policy says so) → scheduled → sent → collecting → closed;
    plus **hold**, **recall** (removes undelivered and marks delivered as withdrawn, no manual file deletion), and a
    **release condition** (e.g. "task T049 done"). Consider aligning states with A2A task states (submitted, working,
    input-required, completed, canceled) for a future A2A mapping.

R3. **Delivery adapters** behind the durable mailbox (the record stays the mailbox file, as in the broker spec):
    nudge to live Claude sessions; **wake-up** of a headless Claude with a declared capability profile (read-only + reply
    path, correct `Edit(path)` syntax, model chosen by policy); Kilo via the kilo-mcp queue with concurrency caps; delivery
    to the canonical copy only (R5).

R4. **Owner decision register**: decisions written only by the owner (CLI or console action, not by an agent), with id,
    date, scope, text; agents cite decision ids instead of relaying "the owner decided". The same register is the owner's
    queue for requests no agent may execute (permission boundaries: a request blocked for one agent goes to the owner,
    never to another agent).

R5. **Host-aware addressing**: the workspace id resolves to the canonical copy (hub after the move, Mac before); writes to
    the non-canonical copy are refused or redirected; the registry records when the canonical copy changed.

R6. **Recipient capabilities declared** in the registry (can write remote? can run headless? permission mode; blind
    policy), so a sender knows before asking and campaigns skip or route accordingly.

R7. **Console view** (initiative 19 / T073): campaigns with receipts, workspaces with move state and blockers, pending
    owner decisions, open questions.

R8. **Web control dashboard** (owner request, 2026-10-30, relayed by ai-coding-tools-1a): one browser page on the hub,
    reached through the SSH tunnel, to **see and act on** everything above:
    - live registry of sessions, workspaces and hosts (R1, R5, R6);
    - campaigns: status per recipient, replies, and **hold / recall / release** buttons (R2);
    - the owner decision register as a **queue the owner answers from the page** (R4);
    - delivery failures (R3), with retry.
    **No parallel UI**: it extends the existing pieces: `ai-orchestration-ui` (127.0.0.1:8780, token + Host allowlist),
    the planned Fleet tab (initiative 18, tasks 18.7-18.8) and the web console of initiative 19 (task 19.15), and inherits
    the security constraints of the multi-machine review §2 B5: the token is not readable by agents; owner-only actions
    (decisions, release of a held campaign, recall) require a human-bound confirmation on the client; no terminal before
    those constraints are solved. R7 becomes the read-only part of this page.

## Priority suggestion

R1 and R2 (with hold/recall) first: they would have removed most of today's manual work. R4 next (trust in relayed
decisions). R3, R5, R6 progressively; R7/R8 as the dashboard on top of them, extending the existing UI.

## Pointers

- kb documents of the run (on the hub, d4science_kb): 08a9846 (analysis), 4f35ecf (proposal, 30 replies, synthesis),
  6c74a8a (design); broadcast draft `service/drafts/2026-10-30-move-development-note.md` (untracked).
- related specs here: `tasks/specs/orchestration-broker-mcp.md`, `multi-machine-development-architecture.md`,
  `orchestrator-control-plane-study.md`, `blocking-questions.md`, `inbox-notes.md`.
