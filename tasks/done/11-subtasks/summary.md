# Summary: 11 - First-class task hierarchy (N levels)

- **Shipped:** 2026-10-23
- **Plan:** [`plan.md`](plan.md)
- **Validation:** closed in bulk on 2026-10-23 (verifier: owner; "Validated by automated test suites and approved by owner for cleanup"); items marked "done with a caveat" had no user session to validate them.

## Outcome

Arbitrary-depth recursive task hierarchies were established across the data model, engine, and interface. The implementation provides atomic leaf transitions, derived container states, parent context injection during execution, legacy plan normalization, closed-apart task archiving, and collapsible tree visualizations.

- **11.1** — Engine: recursive node parser, inheritance, leaf-only transitions, derived container state, container dependencies, structure commands (`child add`, `expand`, `collapse`, `reopen`; no `move`, spec S1): done
- **11.2** — Runs on child tasks: done
- **11.3** — UI: collapsible tree at any depth, node detail with inheritance, add child, expand, move, breadcrumbs: done
- **11.4** — Engine: closed-apart placement at every level (`tasks ship`, `## Closed` section for blocks, link rewriting, `tasks archive`; questions stay in place per S3): done
- **11.5** — Legacy plan normalization: detection, `normalize` run mode, preview/apply: done
- **11.6** — 11.1 review follow-ups: S10 enforcement, full `reopen`, children of `T###`, CLI tests: done

## Deviations

Task 11.5 was added following owner feedback on legacy free-form plans to support detection and plan upgrading, and task 11.6 was added to address review follow-ups on hash enforcement and CLI test coverage.

## Follow-ups

None recorded in the plan.
