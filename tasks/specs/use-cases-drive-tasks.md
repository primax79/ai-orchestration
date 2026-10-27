# Spec — Use cases drive tasks

> **Status:** Draft v2 (2026-10-27), owner request, highest priority. v2 after an independent Codex review (blockers on
> migration, the verification guard and the plan breakdown, all addressed below). Lifecycle model §3: owner question Q011.
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
- **Safety:** the derived rewrite is a targeted header edit of `linked-tasks` only (never the whole-file
  `create_or_update_use_case` path, which loses the validation log); it is part of the `sync-index` plan (preview, plan
  hash, one transaction over all touched files, rollback on failure) and emits one `use_case.links_changed` event per
  use case. It never runs on a tree that fails validation. `adopt-links` is fail-closed: unknown or non-canonical ids
  stop the apply and are listed; the preview shows every task that will gain `use-cases`; a snapshot of all touched
  files is written under `tasks/_reviews/adopt-links-<ts>/` before applying.
- **Header order:** `use-cases` sits after `run-id` and before `short`, `kind` after `size` (existing extension order);
  inserting them must respect it. In initiative blocks the `**Use cases:**` segment is written right after
  `**Depends on:**`; the block rewriter must keep that position (today it appends missing segments at the end).
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
  `kind` stays OPTIONAL in this release: a missing `kind` gives a validate warning only, so existing callers
  (UI backend, VS Code extension, broker `tasks.new`, `orchestration_runs.py`, engine follow-ups, other sessions'
  scripts) keep working; every caller is migrated to pass `--kind` (task 17.4); enforcement, if ever, is a later
  decision.
- **validate warnings:** a `feature`/`fix` task without use cases; a use case with approval `approved` (see §3) and
  no linked task; a task linked to an unknown or `deprecated` use case.

## 3. Use case lifecycle

Two independent fields:

- **`approval:`** `proposed` | `approved` | `deprecated` — the author/owner intent. `use-cases create` writes
  `proposed`; the owner (or the decider) approves. Replaces today's hand-set `status: draft|active|deprecated`
  (migration: draft -> proposed, active/verified/failing -> approved, deprecated -> deprecated).
  *Proposed (owner question Q011):* the note used "draft" both for "no tasks" and for "not yet approved";
  separating them lets a use case be approved before its tasks exist. Migration of today's `status`:
  draft -> proposed; active, verified, failing, partial -> approved; deprecated -> deprecated; the verdict part
  (verified/failing/partial) moves to `last-verdict`, which already exists, so no verdict or log is lost.
- **`stage:`** derived by the engine, never hand-written:
  - `draft` — no linked task;
  - `planned` — linked tasks exist, none started (all open/waiting/blocked/paused);
  - `in development` — work started (at least one linked task in progress, bounced, delivered or later) but not all
    delivered;
  - `ready` — all linked tasks delivered/verified/done (dropped tasks ignored; at least one non-dropped);
  - `verified` / `failing` / `partial` / `untested` — a pure function: stage is `ready` AND the persisted
    `last-verdict` (pass -> verified, fail -> failing, partial -> partial, untested -> untested) AND no
    `revalidation: pending`; with revalidation pending the stage is `ready (revalidation pending)`;
  - all linked tasks dropped -> `draft` (the links are kept, shown as dropped).
- UI, `use-cases list` and the index show `stage` (and approval when not `approved`), never a raw `failing` for a use
  case that is not ready.

## 4. Use-case-first workflow (skills)

task-pipeline (Use Cases section, emergent-task capture) and orchestration-workflow instruct the assistant, when a
user asks for a new feature or task:

1. find related use cases: `ai-orch tasks use-cases search` (new) matches text and actor, the specs a use case
   cites (`Source: tasks/specs/...`), and the use cases linked to tasks that touch the same paths or specs;
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
  `verified`/`done` while one of its approved use cases is `failing`, unless the use case
  passed a probe run AFTER that task was last delivered (remediation-safe: the task that fixes the use case closes once
  the use case passes again; a task that does not fix it stays open). `--owner-approved` overrides, logged. Events:
  `use_case.revalidation_requested`, `use_case.validated` (with forced flag), `task.transition_refused` (reason
  use_case_failing).

## 5b. Supersedes

In `use-case-management-and-ai-validation.md`: the hand-written `status` and writable `linked-tasks` fields are
superseded by §1 and §3 here; that spec gets a "Superseded fields" note (task 17.11).

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
