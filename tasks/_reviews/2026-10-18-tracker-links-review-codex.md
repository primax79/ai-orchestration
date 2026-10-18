# Review of tracker-links.md draft 1 — Codex, 2026-10-18

1. High §4 — file packaging treated as tracker granularity; expand/collapse/move would create or demote issues (tasks_engine.py:2981, :3060). Fix: immutable `projection: issue|line|none` assigned when first mapped; preserved by expand/collapse/archive/move; stable task identity or lineage alias.
2. High §4 — "own unit → issue" reproduces the task tree; conflicts with the method (sub-issue only on assignee/tracker change, SKILL.md:116, :157) and T111 (business units). Fix: D4Science default initiative/business-unit → issue, child task → checklist; explicit overrides for deliberately finer trees.
3. High §4 — mode semantics after apply incomplete (map persistence, unmatched issues, implements vs updates, under). Fix: truth table per mode (reads, proposed writes, persisted links, subsequent sync, unmatched).
4. High §5 — "never send a disabled field" does not prevent T111's loss (T111 README:101: description+notes only, start_date cleared). Fix: preflight non-empty disabled fields; block or require explicit approval; compare full before/after.
5. High §§4–5 — missing read/creation preflight: status_id=*, recursive children, journals, required custom fields and assignees, per-user workflow transitions; 422 = plan defect.
6. High §5 — Redmine has no idempotency keys; timed-out creates may have succeeded. Fix: deterministic local op ids + provenance marker in the issue; checkpoint pending/applied/unknown/failed; reconcile unknown by marker; per-issue updated_on/hash check; stop on first failure, resume.
7. Medium §4 — item tables underspecified vs T111 conditional hierarchy. Fix: immutable row keys, projections lines|issues|issues-when:<predicate>, derived child dimensions; never subject similarity as identity.
8. Medium §§4–5 — notification noise. Fix: one PUT per issue, show expected notification count, sync only at explicit boundaries, second approval above a threshold.
9. High §§3,5 — storage and secrets: commit sanitized plans/mappings/receipts/allowlisted snapshots in tasks/_tracker/redmine/; raw responses/journals in a git-ignored cache; file-based credentials default for D4Science (env fails for GUI launches, SKILL.md:31).
10. High §§2,6 — `tickets` not an allowed header yet and the broker §3b contract is normative without it. Fix: v1 links on initiative/emergent/plan-task nodes, exact serialization, amend engine schema and broker contract together; project/workspace defaults in config, not headers.
11. Medium §§1,5–6 — engine vs agent split inconsistent. Fix: agent/profile proposes matches and text; engine parses, validates, canonicalizes plans, CAS/receipts, invokes a narrow adapter for an approved exact plan; apply owner-facing.
12. Medium §§4,7 — status changes: v1 only proposes, never applies; closed issues frozen, evolution issue with `relates`.

Simpler v1: Redmine only; typed links on logical nodes; immutable projection; two operations (update explicit links; reconcile one container with optional create_missing); agent authors matches/text, engine applies exact approved plan with checkpoints; sanitized committed snapshot; notes/description only, status as proposals; broker fields after revising its contract.

Sound: the four modes cover the owner's cases; typed n:m links with read-only `cites`; repository-as-truth; generated marked blocks; propose-then-apply; ownership checks; readback; unmatched/uncertain sections; deterministic sanitized snapshots; evolve-don't-reopen; no scheduling relations.
