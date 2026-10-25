# Summary: 09 - Inbox: draft notes, reports and screenshots, processed into tasks

- **Shipped:** 2026-10-23
- **Plan:** [`plan.md`](plan.md)
- **Validation:** closed in bulk on 2026-10-23 (verifier: owner; "Validated by automated test suites and approved by owner for cleanup"); items marked "done with a caveat" had no user session to validate them.

## Outcome

The inbox intake system was delivered to capture draft notes, bug reports, logs, and screenshots, and to convert them into structured tasks. Capabilities include engine support for note folders and attachments, authenticated backend uploads, interactive Web UI and VS Code parity, and automated agent-driven triage proposals.

- **09.1** — Engine: note folders, `ai-orch inbox ...`, `tasks new --from-note`: done
- **09.2** — UI backend: inbox endpoints with authenticated uploads: done
- **09.3** — Frontend: Inbox tab, editor with paste and drag-drop images, manual "Convert to task": done
- **09.4** — Agent triage: `triage` run mode, proposal review, accept: done with a caveat: validated by the architect, no user yet
- **09.5** — Frontend: "Process with…" and proposal review: done with a caveat: validated by the architect, no user yet
- **09.6** — VS Code: inbox tab parity (paste and upload through postMessage): done
- **09.7** — Engine: general attachments (text, PDF), `feature` kind, task attachments, convert copies attachments: done
- **09.8** — UI backend: task attachment endpoints and per-class serving: done with a caveat: validated by the architect, no user yet
- **09.9** — Frontend: attachments by class in the note editor and the task detail: done
- **09.10** — Edit proposed tasks before accepting a triage proposal: done
- **09.11** — VS Code: handlers for task attachments and triage (parity with 09.5, 09.8, 09.9): done

## Deviations

Scope was expanded during implementation with tasks 09.7–09.11 to support general non-image attachments (PDFs and logs) on both notes and tasks, in-flight editing of proposed triage tasks before acceptance, and full VS Code bridge parity.

## Follow-ups

None recorded in the plan.
