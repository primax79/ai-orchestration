# Summary: 08 - Blocking questions (format, engine, pending-answers UI)

- **Shipped:** 2026-10-23
- **Plan:** [`plan.md`](plan.md)
- **Validation:** closed in bulk on 2026-10-23 (verifier: owner; "Validated by automated test suites and approved by owner for cleanup"); items marked "done with a caveat" had no user session to validate them.

## Outcome

Structured blocking questions were introduced to allow autonomous agents and developers to pause execution until human architectural decisions are made. The initiative delivered question file formats and validation in the engine, CLI commands (`ai-orch questions`), UI and VS Code dashboard integrations, and notification badge toasts.

- **08.1** — Engine: question files, validator, `ai-orch questions list|show|ask|answer|withdraw`, Decisions region from open questions: done
- **08.2** — Skills: agents file blocking questions in the format: done
- **08.3** — UI backend: question endpoints: done
- **08.4** — Frontend: Decisions tab, navbar badge, task-modal Questions section, ask form: done
- **08.5** — VS Code: "Decisions Waiting" tree from question files: done
- **08.6** — "Answer and resume run": done
- **08.7** — VS Code: toast for new questions and a status-bar badge: done

## Deviations

Amendments after review 2 (Q1–Q10) refined requirements and dependencies across tasks 08.1–08.6. Supervisor question filing in 08.6 was moved to task 07.10, while run resumption was coordinated with initiative 12 (task 12.4). Task 08.7 was added following an owner request for VS Code toast notifications and status-bar badging.

## Follow-ups

None recorded in the plan.
