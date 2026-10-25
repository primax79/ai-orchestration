# Summary: 13 - Doctor rework: findings that are true, actionable and resolvable

- **Shipped:** 2026-10-23
- **Plan:** [`plan.md`](plan.md)
- **Validation:** closed in bulk on 2026-10-23 (verifier: owner; "Validated by automated test suites and approved by owner for cleanup"); items marked "done with a caveat" had no user session to validate them.

## Outcome

The Environment Doctor was reworked based on real machine audit data to eliminate no-op loops and make findings accurate, actionable, and resolvable. The updates introduced a four-tier severity model, cross-assistant finding aggregation, stale plugin detection, history-aware legacy install classification, and persistent hash-based acknowledgment.

- **13.1** — P1-a: stop the no-op "Resolve" loop: done
- **13.2** — P1-b: severity model, cross-assistant grouping, persistent acknowledge: done with a caveat: validated by the architect, no user yet
- **13.3** — P1-c: smarter duplicate resolution: done with a caveat: validated by the architect, no user yet
- **13.4** — P1-d: detect stale plugin copies: done
- **13.5** — P2-a + P2-d: history-aware classification of legacy installs (`outdated-legacy` + "Update"): done with a caveat: validated by the architect, no user yet
- **13.6** — P2-b + P2-c: Kilo effective view; install respects plugins and policy: done
- **13.7** — P3-a..d: stray-file and redundant-MCP actions, `register-mcp` idempotency, agents in the Doctor, trigger-conflict generalization: done with a caveat: validated by the architect, no user yet

## Deviations

None recorded in the plan.

## Follow-ups

Owner decisions from the underlying study were recorded as questions Q002–Q005, with tasks 13.2, 13.3, 13.5, and 13.7 validated by the architect awaiting live user sessions.
