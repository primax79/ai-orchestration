# N071 In-depth study: orchestrator feedback, handoff and reassignment, and a cross-workspace panel (all workspaces: state, messaging, actions)

- id: N071
- title: In-depth study: orchestrator feedback, handoff and reassignment, and a cross-workspace panel (all workspaces: state, messaging, actions)
- kind: request
- status: processed
- created: 2026-10-27T14:45:45.958497+00:00
- author: d4science-kb-3d for the owner (Alfredo), 2026-10-27
- about: N068; N069; specs ui-multi-project.md, orchestration-broker-mcp.md, orchestration-extension-spec.md, events-and-triggers.md; UC028, UC030, UC033, UC037
- produced: T073
- processed-by: ai-coding-tools-c1

Owner request (2026-10-27, verbatim intent): we need a mechanism that gives feedback on the orchestrator, allows handoff and reassignment, etc.; ask for an in-depth study. Owner idea: an additional panel in ai-orchestration listing all existing workspaces, from which you can communicate with them and see their state.

## Why: observed state on 2026-10-27 (no single view, registries disagree)

- Workspace registry (`ai-orch workspace list`): 6 workspaces. ai-coding-tools and d4science-python-library are 'stale'; d4science_kb, gcube_audit, d4science-keycloak and ansible are not registered at all.
- Per-workspace role registries (`ai-orch sessions role`): d4science_kb gen 3 claude interactive (set by hand, see N068); ai-coding-tools gen 1 claude active; smartgears4_migration gen 1 kilo stale; gcube_audit, dave_agent, d4science-python-library, d4science-keycloak have no holder.
- Live sessions as Claude Code sees them (ListAgents): 6 interactive sessions (ai-coding-tools x2, porting-liferay x2, dave-agent, d4science-python-library), named <workspace>-<suffix>. They do not appear in the role registries, and the registries do not know them.
- ~/.config/ai-orchestration/projects/ has 11 project configs, including test leftovers (test_orchestrator_reassign_end0, test_ws, ws, workspace).
- Making this session the orchestrator took: reading orchestrator.json by hand, reassign (phantom headless holder, N068), a second sessions register, and config show with an explicit --workspace (N069). The owner cannot see any of it.

## What the study should cover

1. **Orchestrator feedback**: per workspace, who holds the role (tool, model, kind headless/interactive, provider session), liveness (heartbeat, stale threshold, last turn), queue and cursor, and how a session learns that it is or is no longer the holder. How Claude Code sessions (names from ListAgents), Kilo and Codex sessions map to registry sessions.
2. **Handoff and reassignment** as first-class operations: headless->interactive, interactive->interactive (same or another tool), stale-holder takeover, voluntary hand-off with a handoff prompt from on-disk state, rollback; one generation bump per succession, no phantom sessions; fencing and what the previous holder must do when fenced out. Extend UC028 (headless only today).
3. **Cross-workspace panel** (owner idea): all registered workspaces, plus detection of unregistered ones that have tasks/ or .ai-orchestration/. For each: orchestrator holder and liveness, live sessions, inbox notes to triage, ready queue (UC033), open owner questions, delivered tasks waiting for validation (UC037), last activity. Actions: send a message to the orchestrator or a session (via the broker: orchestration-broker-mcp.md, which superseded peer-messaging.md), request handoff, reassign, register or clean a workspace. Relation with ui-multi-project.md (one workspace and its projects) and orchestration-extension-spec.md (VS Code webview): a new top-level view, or an extension of those.
4. **Registry consistency**: one source of truth or a reconciliation for workspace registry vs per-workspace role registry vs live sessions; cleanup of stale and test entries.
5. **Security and permissions**: messaging and actions from the panel must not bypass per-session permission modes (no cross-session permission laundering); what the panel may do without the owner.

## Expected output

A study document (problem, current pieces and gaps, options with trade-offs, recommendation, use cases to add or change, an implementation plan in initiatives), reviewed by the owner before any implementation. N068 and N069 are concrete cases for it.

---
- Author: d4science-kb-3d for the owner (Alfredo), 2026-10-27
- Workspace: /Users/Alfredo/works/d4science_kb
- ai-orch: 1.1.0 (d6520d1)
- Date: 2026-10-27 14:45:45 UTC
