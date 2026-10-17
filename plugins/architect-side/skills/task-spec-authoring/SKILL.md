---
name: task-spec-authoring
description: "Write task specifications for an Executor agent and calibrate how deeply to verify what it produces - task granularity, the negative-claim rule, reference-drift, caller-tracing, one-task-one-commit, and risk-calibrated verification depth. Protocol-agnostic: applies whether the spec is dispatched through an MCP connector, a CLI wrapper, or handed over by hand - use it whenever a task spec is being written or an Executor's output is being reviewed, not only on any one dispatch path. For the manual/git-worktree mechanics of the CLI path specifically, see the sibling `task-worktree-ops` skill."
---

# Task spec authoring

## Quick Reference

| Field | Value |
| --- | --- |
| **Audience / Role** | Architect / Orchestrator (`deep-reasoning` profile) |
| **When to Load** | Drafting task specifications, designing parallel task batches, or calibrating verification depth for an Executor's output |
| **Execution Modes Supported** | **Single-Framework Native** (parallel native worktrees/subagents) and **Multi-Framework MCP / CLI** |
| **Companion Scripts** | `bin/ai-orch`, `scripts/tasks_engine.py` (`task-pipeline`) |
| **Related Skills** | `task-pipeline`, `orchestration-workflow`, `task-worktree-ops`, `executor-contract` |

## Purpose

An Executor (running on a fast, often-free model) implements quickly -
implementation is rarely the bottleneck. Verification is. This skill
exists to make delegation itself cheap to get right: write specs that are
hard to misimplement, and calibrate how much verification each result
actually needs instead of applying the same amount of scrutiny everywhere.

This grew out of a real multi-hour session independently reviewing nine
Executor-implemented tasks - a cross-file conversion macroplan, roughly
110 call sites across seven files.

## When to use

- Writing a task file (standalone, or as one task inside a
  `task-pipeline`-style plan) that will be handed to an Executor for
  implementation, however that handoff happens.
- Reviewing commits an Executor already produced, deciding what to verify
  and how deeply.

Not for writing the plan's overall structure - use `task-pipeline`
for that (this skill is about the *content* of individual tasks and about
verifying them, not about the `tasks/` tree scaffolding). Its
`references/template.md` already has the file skeleton (Goal / Steps /
Verification) for each task-file shape; the rules below are what to put in
those fields, not a competing template.

Not for the manual/git-worktree mechanics of applying a fix directly
inside an Executor's dedicated worktree, or deciding when it's safe to
touch a branch it's actively working on - see the sibling `task-worktree-ops`
skill for that operational layer.

## Writing the spec: cross-check with other available engines before finalizing

A spec that only one reasoning engine has judged is one uncaught blind
spot away from an expensive mistake discovered mid-execution. When other
independent AI engines are available in the session (other MCP
connectors, CLI tools, agents - whatever the environment exposes),
submit a non-trivial draft spec to them for review before treating it as
final: ask them to find gaps, contradictions, or unstated assumptions,
not just to rubber-stamp it. **Independence doesn't require a different
underlying model** - a fresh, context-blind subagent instance of
yourself, with no memory of having authored the spec, is also a genuine
independent check: the bias removed is authorship bias, not model
identity, so a blind self-review is a legitimate (and often
cheaper/faster) member of the review panel, not a substitute for one
when nothing else is available. Where any reviewer's read disagrees with
yours, work through the disagreement (with them or with the user) rather
than silently picking a side or averaging the two. This costs little compared
to a flawed spec being discovered only after delegated work is already
built on top of it.

This is a cycle, not a fixed two-step: when a round finds blocking
issues, fix the spec and submit the corrected version to the next cycle.
Split the panel rather than treating every reviewer the same on cycle 2+:
**pass most reviewers the prior cycle's findings/summary directly** and
ask specifically whether each fix actually closes its finding and
whether it introduces a new one - that's targeted verification, and
it's what most of the panel should be doing by then. But **keep at least
one reviewer genuinely blind every cycle** (no summary, and an explicit
instruction to ignore any "prior review" link the spec file itself now
carries in its header) - a panel that's fully primed on the known list
tends to check those boxes and stop looking, so an unanchored pass stays
valuable for catching something orthogonal the known list doesn't cover,
not just for the first cycle. Keep cycling until every reviewer comes
back clean, or until you (the orchestrator) judge the remaining
disagreement or residual risk acceptable to proceed on - that judgment
call is yours to make, not a rule requiring literal unanimous sign-off
forever; state the call explicitly when you make it rather than quietly
stopping. One real trial of this (three engines, one non-trivial task
set) had all three independently catch the same transaction-breaking
bug with zero overlap in prompts, plus each engine additionally catching
a distinct real issue the others missed - evidence that the practice
earns its cost more often than "it probably would have been fine."

Within a batch of specs/tasks awaiting this cross-check, don't block
everything on the slowest one: a task with no blocking finding against
its own content, and no dependency on a task that's being corrected
(check this at the file/module level, not just the task-graph level -
two tasks can share no stated dependency yet still edit the same file),
is safe to delegate for implementation while the others go through
another cycle.

## Writing the spec: anchor Goal and Verification to Use Cases

A software system is built to satisfy user scenarios, not just compile code. Therefore, **Use Cases (`tasks/use-cases/UC###-*.md`) are the primary source of truth for both task specifications and acceptance/validation criteria**:

1. **Top-Down Traceability (`Goal` & `Verification`):**
   - The task's **`## Goal`** must explicitly state which Use Case scenario step(s) it fulfills (e.g., `Implements fuel-type query filtering for UC001 (Car Search)`).
   - The task's **`## Verification`** section must be directly derived from the Use Case's acceptance criteria and scenario steps: concrete commands (e.g. API endpoint curls with expected JSON shapes, or automated test commands) that prove the user scenario works.
   - The task header must include `- use-cases: UC001, UC003`.
2. **Bottom-Up Validation:**
   - When all tasks linked to a Use Case are delivered, the Use Case can be tested end-to-end via autonomous AI validation (`./bin/ai-orch use-cases validate UC001`). If gaps are found, emergent tasks (`T###`) are spawned to close them.

## Writing the spec: task granularity is the single biggest lever on defect rate

Narrow, single-module tasks come back clean almost every time. The one
task in the reviewed macroplan that was scoped as a broad
"cleanup/consolidation" pass - touching four already-converted files at
once to remove now-dead code - produced **three real regressions in one
commit**: an import removed from a file that still needed it, a
variable-initialization line moved to the wrong side of the code that
populates it (silently discarding a value on every request), and a
previously-dormant code path made live by a connection-type change,
crashing immediately.

**The sharper rule underneath the file-count proxy**: all three
regressions shared a trait the file-count heuristic only approximates -
correctness depended on a **negative claim** ("this is unused," "this
isn't called elsewhere," "this path is dead"), and negative claims aren't
decidable from a fragment. **If a task's correctness depends on something
not being used/reachable elsewhere, its Verification section must mandate
a full regression-suite run, regardless of how many files the task
touches** - this also catches the single-file case the file-count rule
alone would miss (a one-file change can still rest on an unverified
negative claim about the rest of the codebase).

## Writing the spec: ground everything in real code, and expect drift

Grep-verified call-site counts and line numbers go stale - confirmed
twice in one day in the reviewed session, once from intervening work
between planning sessions, once from a *same-day* merge that shifted line
numbers before the task even started. Never describe code abstractly
("the handler that returns the repositories list"); cite the real
function/line, and write "re-`grep` for `X` before starting, this may have
shifted" directly into any step that cites an exact location.

## Writing the spec: trace who else calls what you're touching

Before writing a task's Steps, grep for every caller of any
function/file it converts or modifies - not just the one file currently
in scope. The hardest bugs in the reviewed session came from a shared
helper whose callers turned out to span two other files the task's
author hadn't traced (converting the helper's signature would have
silently broken both).

This applies doubly to "this UI page's data comes from endpoint X"
claims: verify the actual call chain (frontend service method → HTTP
call → backend route), not just endpoint X's own implementation in
isolation. A real mistake in the reviewed session targeted an endpoint
that matched the docs description and the URL's own name, but that the
UI never actually called - the fix landed correctly against the (wrong)
spec and changed nothing real.

## Writing the spec: one task, one commit

Note explicitly in the task file that it should result in one commit
scoped to just that task's changes - an agent working continuously
across several tasks may otherwise sweep up unrelated pending work
(another task's draft, an unrelated doc addition) into the same commit.
The Executor's own behavioral contract (`executor-contract`) is
what must actually honor this at commit time; this is the spec-side half -
say it explicitly so there's something to hold the Executor to.

## Writing specs for a batch of parallel tasks

Tasks dispatched in parallel branch from the same commit and cannot see each
other. Four things in the spec turn the merge from painful into cheap:

- **Give each task a disjoint write scope, down to the directory** - not "work
  in library X" but "only `library-x/src/<your-subdir>/`, and nothing else."
- **Name the one shared file they may all touch, and constrain how.** A
  barrel/index file is usually unavoidable: tell every task to add exactly its
  own export line and to reformat nothing else. The conflict then lands in one
  known file and resolves in seconds instead of spreading across the batch.
- **Disjoint directories do not prevent name collisions.** Two tasks writing
  different subdirectories of the same library can still export the same type
  name, and each is green on its own. When several tasks in a batch touch one
  library, pre-assign the shared vocabulary in the specs (say which task owns
  `BBox`, `TileKey`, ...) or expect to resolve it at integration - but plan for
  it rather than discover it.
- **Pin the toolchain in the spec and in your own verification commands.** If
  the project needs a runtime version the machine's default shell doesn't
  provide, set it explicitly in the delegation environment *and* in every
  command you run to check the result. A default shell on the wrong major
  version produces failures that look like the task's fault and aren't.

One more that only appears when a formatter is in the batch: **a task that
establishes a formatting baseline conflicts with every sibling by
construction**, since they all branched before it existed. Merge it last, then
run the formatter once over the integrated result as a separate, clearly
labelled commit.

## Verifying the result: match depth to risk, don't verify everything the same way

- **Single-module conversion, narrow scope**: diff review against the
  spec, plus one functional smoke test. That's enough.
- **Any task resting on a negative claim** (see above), regardless of file
  count: full regression sweep, every time - this is exactly the category
  that produced real bugs in the reviewed session, and where the cost of
  thorough review is actually justified.
- **Once an automated test suite exists for the project**: every task
  touching source code should end with "run the suite, confirm green" as
  an explicit Verification step in the task file itself. This is the
  single highest-leverage way to close the gap between a fast/free
  implementation agent and a slower manual-verification process - it
  turns most of what used to require live-server-spinning and manual
  diffing into a ten-second automated check, runnable by the reviewer *or*
  by the Executor itself as a self-check before declaring a task done.
- **Always test against disposable copies** of real data/databases - never
  the real files. An implementation agent may be running its own live
  process against the real data concurrently; a verification script
  pointed at the real file can hang on lock contention or corrupt shared
  state.

## Verifying the result: recognize when the Executor improves on the spec

Check outcome and reasoning, not literal compliance with the spec's
letter. In the reviewed session, one task was told "leave these four
functions permanently unconverted, to avoid breaking two other callers
that pass a different connection type." The Executor instead made the
four functions dual-compatible via duck-typing on the connection type -
which is strictly *better*: it preserved every existing caller **and** let
the rest of the codebase modernize, which the prescribed fix would have
permanently blocked. Don't mark that down as "didn't follow instructions"
- verify it actually works both ways and credit it.
