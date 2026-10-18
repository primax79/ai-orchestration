# Review of peer-messaging.md (draft 1) and events-and-triggers.md §0a — Codex, 2026-10-18

Read-only review (Codex MCP, sandbox read-only). Outcome: draft 1 superseded by `../specs/orchestration-broker-mcp.md`,
which addresses the items as noted there (Codex 1–12).

1. Blocker — untrusted mail entered a persistent privileged session; quoting is not a boundary; Kilo has no sandbox equivalent. Fix: quarantine with a stateless no-tools classifier; owner approval before reading refs or substantive replies.
2. Blocker — triggers enqueue `<seq>.json` without the orchestrator lock and advance the role cursor on enqueue (orchestration_triggers.py:938, :947, :1762; orchestration_orchestrator.py:627, :1372). Filed as T026.
3. Major — mailbox delivery lacked a concurrency/recovery protocol (no-replace, receipts separate, fsync, idempotency ledger).
4. Major — the promised event-lock timeout does not exist (orchestration_events.py:101 blocking flock).
5. Major — no `peer_message` turn type; reduced turns cannot call ai-orch; outputs are not parsed into proposals. Fix: structured result schema applied by trusted core code.
6. Major — daemon ownership contradictory (§0a serve vs §5 triggers daemon).
7. Major — concurrent `ensure` can overwrite config (hash checked before config_lock, orchestration_config.py:2419, :2436).
8. Major — stopped/crashed/missing underspecified; `status` auto-registers (orchestration_orchestrator.py:541, :547).
9. Major — worker-crash retry can duplicate mutating owner turns (orchestration_orchestrator.py:1030, :1047, :1112). Fix: outcome_unknown.
10. Major — derived ids collide; renames break lookups; symlinked paths. Fix: immutable uuid, canonical path/inode checks.
11. Major — blind isolation TOCTOU between policy read and write; default deny for unconfigured targets.
12. Minor — secret scanning overstated; amendments leave superseded text in the base sections.

Sound: durable tool-neutral records; stable workspace addressing; no attachments in v1; receiver-owned policy, provenance, bounded bodies, proposal gates. Simpler alternative suggested: a single per-user broker/store.
