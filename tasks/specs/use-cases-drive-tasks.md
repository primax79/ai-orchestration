# Spec — Use cases drive tasks

> **Status:** Draft v1 (2026-10-27), owner request, highest priority.
> **Drives initiative:** 17 (`tasks/17-use-cases-drive-tasks/plan.md`).
> **Source:** inbox note N072 (`_inbox/analyzed/20261027-144719-use-cases-drive-tasks-dependency-from-us/note.md`)
> including the owner additions; N067 (campaign fails draft use cases) and T069 are a first slice of §5.
> **Extends:** `use-case-management-and-ai-validation.md` (use case format, AI validation, campaigns).

## 0. Why

In git-code-rag two campaigns (2026-10-25, 2026-10-27) marked 39/41 and then 9 post-v0 draft use cases as `failing`:
the campaign ran every use case, including ones whose tasks do not exist or are not delivered. The owner read it as a
broken product. Root cause: the link between tasks and use cases is a free list on the use case
(`linked-tasks`), an optional `use-cases:` on tasks, and nothing uses either.

Owner decisions (2026-10-27): use cases drive tasks; tasks originate from use cases; a use case depends on its tasks;
the relation is many-to-many; new work follows a use-case-first workflow.

## 1. The link (many-to-many, one source of truth)

- **Source of truth: the task.** Emergent tasks: header `use-cases: UC001, UC004` (already in the closed header set).
  Initiative tasks: a `**Use cases:** UC001, UC004` segment in the block's status line, after `**Depends on:**`.
- **Derived: the use case.** `linked-tasks:` on the use case is rewritten by the engine from the tasks (like the
  generated rows of `00-INDEX.md`), sorted, on every `sync-index` and on every mutation that changes a task's
  `use-cases`. A hand edit of `linked-tasks` is overwritten; `validate` warns about a manual difference before sync.
- **Migration (one-time):** `ai-orch tasks use-cases adopt-links` (preview, then `--apply --expect-plan-hash`) copies
  each use case's current `linked-tasks` onto the referenced tasks' `use-cases` (union, never removing), so no link
  is lost when the direction flips. Unknown ids are reported, not created.
- **Scope:** ids in the same `tasks/` tree. Cross-workspace refs (`workspace:<name>/<id>`) are allowed on the task
  side and listed on the use case as written, not resolved (v1).
- **Commands:** `tasks link <task> UC###[,UC###]`, `tasks unlink <task> UC###` (both preview/apply like other
  mutations); `tasks show` lists the task's use cases with their stage; `use-cases show` lists linked tasks with states.

## 2. Tasks born from use cases

- `ai-orch tasks new --use-case UC001,UC004 ...` links at creation. `--from-use-case UC001` also pre-fills: title
  (from the use case title, editable), Goal (scenario steps the task covers: all by default, or `--steps 2-3`),
  Verification (the use case's acceptance criteria and probe command). Same options for creating an initiative task
  block (`tasks child` / plan task creation).
- **Kind.** Tasks carry `kind:` (existing optional field). Values used here: `feature`, `fix`, `chore`, `docs`,
  `investigation`. `tasks new` defaults `kind` to `feature` when `--use-case` is given or asks for it otherwise
  (non-interactive: `--kind` required unless `--use-case` is given; legacy tasks without `kind` are not checked).
- **validate warnings:** a `feature`/`fix` task without use cases; a use case with approval `approved` (see §3) and
  no linked task; a task linked to an unknown or `deprecated` use case.

## 3. Use case lifecycle

Two independent fields:

- **`approval:`** `proposed` | `approved` | `deprecated` — the author/owner intent. `use-cases create` writes
  `proposed`; the owner (or the decider) approves. Replaces today's hand-set `status: draft|active|deprecated`
  (migration: draft -> proposed, active/verified/failing -> approved, deprecated -> deprecated).
  *Architect decision (owner may override):* the note used "draft" both for "no tasks" and for "not yet approved";
  they are separated so a use case can be approved before its tasks exist.
- **`stage:`** derived by the engine, never hand-written:
  - `draft` — no linked task;
  - `planned` — linked tasks exist, none started (all open/waiting/blocked/paused);
  - `in development` — at least one linked task in progress/bounced, or some delivered and some not;
  - `ready` — all linked tasks delivered/verified/done (dropped tasks ignored; at least one non-dropped);
  - `verified` / `failing` — set only by a probe run (`use-cases validate`, campaign, AI validation) on a `ready`
    use case; a later change of a linked task (§5) moves it back to `ready` with `revalidation: pending`.
- UI, `use-cases list` and the index show `stage` (and approval when not `approved`), never a raw `failing` for a use
  case that is not ready.

## 4. Use-case-first workflow (skills)

task-pipeline (Use Cases section, emergent-task capture) and orchestration-workflow instruct the assistant, when a
user asks for a new feature or task:

1. find related use cases (text, actor, linked specs and tasks: `ai-orch tasks use-cases search` — new, simple
   text + actor match);
2. propose updates to them, or point out contradictions between the request and existing use cases (scenario,
   acceptance criteria, scope), and/or draft missing use cases (`approval: proposed`);
3. get them approved by the user/decider (a Q### question when the user is not in the conversation);
4. only then write or update specs and create the tasks, each linked (`--use-case`).

Skipping to tasks is allowed for `chore`, `docs`, `investigation`; the skill says so. Generated skill files are
edited through their templates/bindings.

## 5. Validation gating and regression

- `use-cases validate <UC>` refuses (exit 2, message "not ready (N/M tasks done)") unless the use case is `ready`,
  `verified` or `failing`, or `--force` is given (recorded as forced in the validation log).
- Campaigns run only in-scope use cases (`ready`/`verified`/`failing`); the report lists the others under
  "Not ready" with N/M and their stage, and does not touch them. Readiness score = verified / in-scope.
  Probes that cannot run (missing command or test file, timeout) give `untested`, not `failing` (T069).
- **Regression:** when a task linked to a `verified` use case is delivered again, reopened, or bounced, the use case
  gets `revalidation: pending` and appears in `ai-orch tasks use-cases queue` (and in the UI). A task cannot reach
  `verified`/`done` while one of its approved use cases is `failing`, unless `--owner-approved` (logged).

## 6. Non-goals (v1)

`depends-on` between use cases (N072 point 6) and its graph view; resolving cross-workspace task refs.

## 7. Acceptance

1. Links: `tasks link`/`new --use-case` -> the use case's `linked-tasks` updated on sync; hand edit overwritten with a
   validate warning first; `adopt-links` loses no existing link.
2. `--from-use-case` pre-fills Goal/Verification from the use case.
3. Stage derivation for each stage (fixtures with tasks in every state; dropped ignored).
4. Campaign on 2 ready + 2 draft + 1 in-development use cases: only the 2 ready are probed; others under "Not ready".
5. Regression: reopen a task of a verified use case -> `revalidation: pending`, queued; task to verified refused while
   a linked use case is failing.
6. Skill text: the use-case-first steps present in task-pipeline and orchestration-workflow (generated files
   regenerated, `--check` clean).
7. Real data: git-code-rag tasks tree (copy): after `adopt-links`, its 41 use cases show stages, a campaign probes only
   ready ones (none of UC031-UC040).
