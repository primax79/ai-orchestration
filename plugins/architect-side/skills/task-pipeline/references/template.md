# Templates - `tasks/` pipeline file skeletons

Copy-paste skeletons for every file kind. Keep the cross-links (`Drives` /
`Derived from`) current, and apply progressive disclosure - don't repeat
shared-context content inside a spec or task.

---

## `tasks/AGENTS.md` (the convention, dropped once per project)

A project-local copy of the task-management convention so the repo is
self-contained for agents/teammates without this skill. Mirror the
`task-pipeline` SKILL: the structure, the raw→spec→plan→summary pipeline,
the task-packaging rule (inline vs one-file-per-task by size), the emergent-task
rules (capture first, ids, the three files, states, several sessions), the core
rules, and the delegation rules. Keep it short and point to `00-INDEX.md` for live
state and `CONTEXT.md` for project facts.

---

## `tasks/CONTEXT.md` (shared, project-wide durable context - read first)

```markdown
# Project context (shared)

Durable, project-wide grounding shared by every initiative. Read before any
spec or plan. Re-verify anything load-bearing against the real files - this
drifts between sessions.

## Codebase map
- <top-level layout: which dir does what; key entry points>
- <annotate additions: "added by initiative NN">

## Command / API / data surface
- Build/test/run: `<commands>`
- <key services/tokens/endpoints/schemas an initiative will reuse>

## Cross-cutting locked-in decisions
- **<decision that spans initiatives>** - *why* (constraint/trade-off).
- <e.g. "dynamic-viewer stays 100% domain-agnostic - never import @is/*">

## Conventions
- <repo-wide norms: language for code/strings, commit style, verification gate>
```

---

## `tasks/00-INDEX.md` (live registry)

```markdown
# Task Index

Live registry of planned and in-progress development. For how this directory
works see [`AGENTS.md`](AGENTS.md); for shared project facts see
[`CONTEXT.md`](CONTEXT.md). This file is the state: what exists, priority, status.

## Initiatives

`#` is the stable id (folder/task prefix, e.g. `04.2`); it is NOT reading
order - `Priority` is.

| Priority | # | Initiative | Status | Depends on | Size |
| --- | --- | --- | --- | --- | --- |
| 1 | 01 | [<name>](01-<slug>/plan.md) | open / partial / ✅ done → `done/` | - | M |

## Specs

| Spec | Drives |
| --- | --- |
| [<slug>](specs/<slug>.md) | 01, 03 |

## Next up

| Id | Priority | Task | Executor | Handoff |
| --- | --- | --- | --- | --- |
| T012 | P0 | [<title>](<category>/T012-<slug>.md) | self | `Read tasks/<category>/T012-<slug>.md, do it, update the task and the registry.` |

## Tasks by category

### <category>

<goal of the category, one line>. Owner session: <name or unassigned> ([README](<category>/README.md)).

| Id | Priority | Task | State | Executor | Depends on |
| --- | --- | --- | --- | --- | --- |
| T012 | P0 | [<title>](<category>/T012-<slug>.md) | open | self | - |
| T015 | P1 | [<title>](<category>/T015-<slug>/README.md) | blocked | <agent> | T012 |

## Decisions waiting

<!-- ai-orch:generated decisions -->
| Key | Question | Blocks | Decider | Recommended |
| --- | --- | --- | --- | --- |
| [Q001](questions/Q001-<slug>.md) | <short question ending with ?> | T013 | owner | A |
<!-- /ai-orch:generated decisions -->

## Done

| Id | Task | Result | Closed |
| --- | --- | --- | --- |
| T009 | [<title>](done/<category>/T009-<slug>.md) | done / done with a caveat / dropped | <date> |

## Dependency graph

​```text
01 ──► 03 ──► 04
02 (independent)
​```

---

Delegation rules, the pipeline, and the folder convention live in [`AGENTS.md`](AGENTS.md).
```

---

## `tasks/<category>/README.md` (one per category of emergent tasks)

```markdown
# <category>

owner-session: <name, or unassigned>

## Goal and scope

<what this category must achieve, and what kind of work belongs here>.
State and priority of its tasks are in `tasks/00-INDEX.md`; working notes are
in `notes/` next to this file.

## Start a session on the whole category

> Read tasks/<category>/README.md and its tasks in priority order, set
> owner-session, work the tasks one at a time (P0 first), and keep the task
> files, this README and tasks/00-INDEX.md current.

## Rules

- Only the owner session edits the task files and this README; others add
  notes below or create new T### tasks.
- A finished task moves with `git mv` to `tasks/done/<category>/`, same name.

## Shared notes

- <date, session>: <note>
```

---

## `tasks/<category>/T###-<slug>.md` or `T###-<slug>/README.md` (emergent task: definition)

A small task is the single file; a task with context or progress is the folder,
and this is its `README.md`.

```markdown
# T### <title>

- id: T###
- title: <title>
- category: <category>
- priority: P1
- priority-reason: <one line>
- next-up: no
- state: open
- executor: self | <agent product> | dedicated-session | user-decision | <person>
- depends-on: - | T### | NN.T
- decider: - | Q### (or legacy: owner: <question>)
- sources: <conversation of <date>, file, finding, raw row id>
- paths: <repositories and paths the task touches>
- handoff: Read tasks/<category>/T###-<slug>.md (or T###-<slug>/README.md for a folder task), do the open steps, run the Verification, update the task and the registry.
- profile: bulk-execution | deep-reasoning | orchestration | exploration   # optional orchestration extension field
- verification-mode: independent-session | cross-agent | panel | owner | self  # optional orchestration extension field
- verifier: - | <tool>:<profile> | blind-subagent:<profile> | owner            # optional orchestration extension field

## Goal

<the outcome, in one or two sentences>

## Steps

1. <step>

## Verification

- <runnable check, with its expected result>
```

The 13 core header fields are closed and in this exact order; empty values are `-`.
Optional orchestration extension fields (`profile`, `verification-mode`,
`verifier`) may follow immediately after `handoff`. While `delivered`, add a
body line right after the header: `verification pending: <what is left, by
whom>`. States: `open | in progress | waiting | blocked | delivered | bounced |
verified | done | done with a caveat | dropped`. `verified` is set by someone
other than the executor (`verifier != executor`), or by the executor after the
user's explicit approval (recorded in `PROGRESS.md`). Manage transitions and
`00-INDEX.md` synchronization deterministically with `scripts/tasks_engine.py`.

---

## `tasks/<category>/T###-<slug>/CONTEXT.md` (resume without the original session)

```markdown
# T### - context

- **Where the work is:** <repo, branch, paths>
- **Build and check:** `<commands>`
- **Rules from the user:** <constraints given in conversation>
- **Established facts:** <fact> (`<command or file that established it>`)
```

---

## `tasks/<category>/T###-<slug>/PROGRESS.md` (log and open items)

```markdown
# T### - progress

## Open

- [ ] <item>

## Log (newest first)

- <date>, <session>: <what was done, what was found, the next step>
```

---

## `tasks/questions/Q###-<slug>.md` (blocking question)

```markdown
# Q### <title>

- id: Q###
- question: <short standalone question <= 160 chars ending with ?>
- status: open
- blocks: - | T### (in progress)
- decider: owner
- asked-by: <tool>:<profile> | owner
- asked: <YYYY-MM-DD>
- origin-run: -
- open-answer: yes | no
- recommended: A | -

## Context

<self-sufficient explanation of the stakes and trade-offs>

## Options

- **A** — <label>: <consequence>
- **B** — <label>: <consequence>

## Answer

- choice: -
- answered-by: -
- answered: -
```

---

## `tasks/specs/<slug>.md` (structured spec - the *what & why*)

```markdown
# <Title> (spec & context)

> **Drives initiative(s):** [NN](../NN-<slug>/plan.md)  ·  raw sources: `../_inbox/`

## Goal
<the outcome, grounded in a concrete problem - quote the real offending
code/data, don't describe it abstractly>

## Current state (verified <date> - re-check before starting)
<what exists today: files, behaviour, the real symbols involved>

## Locked-in decisions
- **<decision>** - *why* (the trade-off/constraint that drove it).
- <open forks stay as `[DECISION] …` and name the task that must resolve them>

## Non-goals
- <what this explicitly does NOT do, and why - prevents scope creep>
```

---

## `tasks/use-cases/UC###-<slug>.md` (use case specification & validation target)

```markdown
# UC### - <Title>

- id: UC###
- title: <Title>
- actor: <End-User | Developer | Operator | Buyer>
- status: <draft | active | verified | failing>
- priority: <P0 | P1 | P2 | P3>
- linked-tasks: <NN.T, T### or ->
- verification-type: <automated-probe | e2e | code-audit | api-probe>
- last-tested: -
- last-verdict: -

## Description & Business Value
<Who is the actor, what do they want to accomplish, and what business/user value does it deliver?>

## Preconditions
- <Environment, running server port, database seed data, or active services needed>

## Scenario / Interaction Steps
1. <Actor performs action or calls endpoint>
2. <System responds with expected behavior>
3. <Boundary checks or error cases>

## Automated Verification Command
```bash
<runnable probe: curl command, pytest call, or test script>
```

## Acceptance Criteria
- [ ] <Observable acceptance criterion 1>
- [ ] <Observable acceptance criterion 2>

## AI Validation Log
```

---

## `tasks/NN-<slug>/plan.md` - INLINE form (small/medium initiative)

```markdown
# <Title> - Implementation plan

> **Derived from spec:** [../specs/<slug>.md](../specs/<slug>.md)

## Tasks

### NN.1 - <task name>
**Goal**: <one sentence>.
Steps:
1. <real file/function names, real snippets - not "update the parser somehow">
2. ...
Verification: <runnable check; specific inputs/outputs or command>.

### NN.2 - <task name>
...
```

---

## `tasks/NN-<slug>/plan.md` - EXPANDED form (large / delegated initiative)

`plan.md` becomes the index; each task is its own file.

```markdown
# <Title> - Implementation plan

> **Derived from spec:** [../specs/<slug>.md](../specs/<slug>.md)

Tasks (each = one commit; hand one file at a time to a delegated agent):

1. [NN.1 - <task name>](NN.1-<name>.md)
2. [NN.2 - <task name>](NN.2-<name>.md)

Shared decisions for this initiative that every task must honour:
- <initiative-local locked-in decision - *why*>
```

### `tasks/NN-<slug>/NN.T-<name>.md` (one expanded task)

```markdown
# NN.T - <task name>

> Part of [<Title>](plan.md) · spec: [../specs/<slug>.md](../specs/<slug>.md)

**Goal**: <one sentence>.

Steps:
1. <concrete, grounded steps>
2. ...

Verification: <runnable check>.
```

---

## `tasks/NN-<slug>/summary.md` (completion record)

```markdown
# NN - <Title> (completion summary)

**Status:** ✅ Completed and merged into `<branch>`.

- Implementation commit(s): `<sha>` (<message>)
- Merged via: `<sha>` (if applicable)

## What landed
<net effect on the branch: files, key changes; `git diff --stat A B` figures>

## Deviations from the plan
<anything done differently and why; conflicts resolved; tasks dropped/added>

## Verification
<what was run/checked; what to spot-check when next running the app>
```
