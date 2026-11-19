# N096 URGENT P0 (part of N094): header field 'tracker' as a list of ticket links, clickable in every interface

- id: N096
- title: URGENT P0 (part of N094): header field 'tracker' as a list of ticket links, clickable in every interface
- kind: request
- status: processed
- created: 2026-11-19T17:11:48.808020+00:00
- author: porting-liferay
- about: N094
- produced: T091
- processed-by: claude (ai-orchestration maintainer session, 2026-11-19)

**Priority: P0, URGENT, part of N094 (owner Alfredo, 2026-11-19).** Please handle it together with the `tracked` state.

## Request

A dedicated optional header field for the external tickets of a task, as a **list of links**, rendered as clickable
links by every interface (web UI, VS Code extension, `tasks show`), and used by the tracker sync.

Proposed: `tracker` (after `handoff` among the optional extensions), value a comma-separated list of full URLs, optionally
with a label:

`- tracker: https://support.d4science.org/issues/34152, https://support.d4science.org/issues/34153`

(or Markdown links `[#34152](https://...)` if the format prefers labels; either way the URL is complete, never a bare `#N`).

## Expected behaviour

- Header parser and `validate` accept the field (list, each item a URL; empty `-`).
- UI / extension / `tasks show` render each item as a link that opens the ticket.
- Registry: the task row can show the ticket links (or a count).
- `tracker-sync --dry-run` (N094 follow-up): reads every listed ticket; proposes closing the task only when **all** its
  tickets are closed (Closed / Completed / Rejected), `dropped` when all are Rejected; Redmine REST first, adapter-based.
- A task in state `tracked` should have a non-empty `tracker` (validate warns otherwise).

## Context

porting_liferay rule today (tasks/AGENTS.md, "Redmine link"): first body line `Redmine: [#N «title»](URL), ...`, to be
moved into this field when it exists. Several tasks follow more than one ticket (bug + sub-tickets, development + deploy).

---
- Author: porting-liferay
- Workspace: /Users/Alfredo/works/gcube/porting_liferay
- ai-orch: 1.1.0 (2965604)
- Date: 2026-11-19 17:11:48 UTC
