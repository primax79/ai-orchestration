# Summary: 10 - Abstract timeline: dependencies and priorities

- **Shipped:** 2026-10-23
- **Plan:** [`plan.md`](plan.md)
- **Validation:** closed in bulk on 2026-10-23 (verifier: owner; "Validated by automated test suites and approved by owner for cleanup"); items marked "done with a caveat" had no user session to validate them.

## Outcome

Dependency tracking, topological column ordering, and priority-driven execution pipelines were implemented for the task graph. The system added cycle detection, critical path calculation, microtasks with reduced headers, and multiple backlog views (Queue, Kanban, Tree, and Timeline) across Web UI and VS Code.

- **10.1** — Engine: `tasks graph` (columns, ready queue, heaviest chain, Mermaid), `size` field, `tasks set-priority`, `tasks set-size`, `tasks set-deps`, cycle check: done
- **10.2** — UI: graph and edit endpoints and the Timeline tab (arrows, ready queue, priority and dependency editing): done
- **10.3** — VS Code: Timeline in the webview: done
- **10.4** — Engine: microtasks (`micro` category, reduced schema, `tasks micro`, `tasks promote`, XS size), kind and labels: done
- **10.5** — UI: microtask quick-add, XS pills, "Promote", kind and labels, shared filter bar: done
- **10.6** — Backlog views: compact "Next up", separate view switcher (Queue, Kanban, Tree, Timeline): done

## Deviations

Task 10.6 was introduced based on owner feedback to replace the monolithic Next Up view with a compact Queue and a persistent multi-view switcher.

## Follow-ups

None recorded in the plan.
