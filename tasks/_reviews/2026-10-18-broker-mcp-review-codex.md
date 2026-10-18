# Review of orchestration-broker-mcp.md draft 3 — Codex, round 2 (2026-10-18)

## Round-1 disposition
Resolved: C1, C2 (design; T026 implements), C5, C6, C8, C9, C10, C11, C12, G1, G2, G4–G12. Partial: C3 (crash recovery across stores), C4 (offline CLI path has no timeout contract), G3 (per-adapter enforcement mechanism unspecified). Not resolved: C7 (no under-lock config CAS for concurrent `ensure`).

## New findings
1. Blocker §3/§5 — broker recovery: crash can leave applied writes with lost responses, running children, classifier jobs, tickets of unknown status. Fix: supervised restart, SQLite WAL, durable ticket/job states, idempotency keys, startup reconciliation, outcome_unknown for every interrupted mutation.
2. Blocker §3 — offline CLI split-brain: broker-internal locks do not exclude an offline CLI (tasks_engine.py:299 `.ai-orch.lock`). Fix: broker and CLI take the same project lock; file-hash CAS; broker singleton/readiness lock; explicit `--offline` refused while the broker owns the workspace.
3. Major §4 — confirm_token undefined (expiry, single use, caller binding, args/plan/file hashes, replay). Fix: persisted single-use token bound to caller, tool, canonical args, uuids, plan hash and file hashes; short expiry; terminal receipt for replays.
4. Major §3/§4 — MCP client feasibility assumed (auto-start, readiness, reconnect, resources, _meta, long tickets); caller cwd unsafe for a global broker. Fix: interoperability spike with Claude, Kilo, Codex as a migration gate; bind workspace/project at registration or require them explicitly.
5. Major §1 — qualified ids incompatible with the engine's depends-on parsing (tasks_engine.py:227, :953, :5848). Fix: one QualifiedTaskRef grammar, reject malformed prefixes, namespaced graph keys, remote dependency/cycle semantics.
6. Major §1/§2 — project discovery underdefined (ids, duplicates, renames, symlinks, nested trees; engine takes one tasks_dir, tasks_engine.py:2253). Fix: explicit projects in config for v1 with immutable uuid + slug; scanning only proposes registrations.
7. Major §6 — console identity not durable (collisions, hijack, reconnect); unread_mail envelope not defined as MCP content vs metadata; idle Kilo/Codex consoles get nothing. Fix: broker-issued console uuid + secret, lease, stable mailbox, explicit mail.poll.
8. Major §7 — classifier cost/failure policy missing. Fix: deterministic validation first, durable pending_classification, bounded timeout/retries/cost, fail closed to manual review, separate budgets.
9. Major §9 — migration order allows mixed writers and late discovery. Fix: invariants/recovery + client spike → shared locking/idempotency → explicit registry/read-only broker → deterministic writes → switch CLI/skills incrementally → durable orchestrator.ask → workspace mail → consoles/classifier/UI.
10. Minor — header says draft 2.

## Simpler v1 (Codex)
Per-user broker (SQLite WAL, supervised, stdio shims), explicit workspace/project registration; task trees stay project-local (broker routes qualified ids, on-disk depends-on stays local; cross-project deps in v2); read tools + hardened deterministic writes + durable orchestrator.ask tickets; durable mailbox with allow/deny, body and rate limits (workspace → orchestrator, consoles by explicit registration and polling); no auto classifier in v1 (unattended orchestrators get safe metadata only, raw body quarantined until explicit acceptance). Defer discovery, cross-project graphs, mail badges in envelopes, classifier-driven turns, attachments, reactive notifications.
