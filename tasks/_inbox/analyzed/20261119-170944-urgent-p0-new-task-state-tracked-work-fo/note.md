# N094 URGENT P0: new task state 'tracked' (work followed on an external tracker), start implementation now

- id: N094
- title: URGENT P0: new task state 'tracked' (work followed on an external tracker), start implementation now
- kind: request
- status: processed
- created: 2026-11-19T17:09:44.853614+00:00
- author: porting-liferay
- about: porting_liferay tasks/AGENTS.md Redmine link rule
- produced: T091
- processed-by: claude (ai-orchestration maintainer session, 2026-11-19)

**Priority: P0, URGENT (owner Alfredo, 2026-11-19). Please start the implementation right away.**

## Request

Add a new canonical task state for work that is tracked on an external issue tracker and owned by someone else:
the local task stays open only as a link, and is closed when the ticket is closed.

Proposed name: `tracked` (alternatives: `external`, `on-tracker`). Parameterized form like the other states:
`tracked (Redmine #34152, NetFarm)`.

## Why

porting_liferay is being handed over to another maintainer. Of ~96 open tasks, a large part are local mirrors of work
that lives on Redmine tickets assigned to others (vendor NetFarm, IAM team, ops). Today they can only be `waiting`,
which mixes two different situations:

- `waiting`: the work is ours, we need something from someone to continue;
- `tracked`: the work is not ours any more; nothing to do locally until the ticket closes.

Without the distinction the registry cannot say "X tasks are ours, Y follow a ticket", which is what the handover needs.

## Expected behaviour

- `CANONICAL_STATES` gains `tracked`; `normalize_state` accepts `tracked (<ref>, <owner>)`.
- Transitions: `open|in progress|waiting|blocked|paused -> tracked`; `tracked -> done | done with a caveat | dropped`
  (ticket closed / rejected); `tracked -> open | in progress` (ticket comes back to us).
- Not terminal; counted separately in the registry (own column or section, e.g. "Seguiti su tracker").
- `tasks validate` accepts it; container derivation treats it like `waiting`.
- Nice to have (can follow): a header/body convention for the ticket reference (e.g. body line `Redmine: #N «title»`, or
  an optional header field `tracker: redmine#34152`) and `tasks tracker-sync --dry-run` that reads the tracker state and
  proposes closing the tasks whose ticket is closed (Redmine REST first; read-only by default).

## Context

- Project rule already written in porting_liferay `tasks/AGENTS.md` ("Redmine link", 2026-11-19).
- Interim workaround there: `waiting (Redmine #N, <owner>)`, to be converted when `tracked` exists.
- Related analyzed note: `_inbox/analyzed/20261021-081656-cross-workspace-executor-and-depends-on-` (remote work tracked elsewhere).

---
- Author: porting-liferay
- Workspace: /Users/Alfredo/works/gcube/porting_liferay
- ai-orch: 1.1.0 (2965604)
- Date: 2026-11-19 17:09:44 UTC
