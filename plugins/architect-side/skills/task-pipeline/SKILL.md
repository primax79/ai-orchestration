---
name: task-pipeline
description: "Author and maintain a durable, resumable development pipeline as a `tasks/` tree - raw input (`_inbox/`) distilled into structured specs (`specs/`, many-to-many with initiatives), each generating or updating an initiative (`NN-<slug>/plan.md`, tasks sized one-per-commit) that ships with a `summary.md` and moves to `done/`, over a shared `CONTEXT.md` and a live `00-INDEX.md` registry. Also the place where work that EMERGES during a conversation is captured (`<category>/T###-<slug>/` with README/CONTEXT/PROGRESS, unique ids, priority with a reason, any executor: this session, a delegated agent, a person), so it never lives only in a session's context. Use when planning work too large for one sitting, spanning multiple sessions or dependent features, or delegated piecemeal to another agent (e.g. Kilo), and whenever a new to-do, follow-up or finding appears mid-session. Not for a single-session, single-file change - use a normal plan for that."
---

# Task pipeline authoring (`tasks/` tree)

## Quick Reference

| Field | Value |
| --- | --- |
| **Audience / Role** | Architect / Orchestrator (`orchestration` profile) |
| **When to Load** | Structuring a multi-task `tasks/` pipeline, capturing emergent mid-session tasks (`T###`), transitioning task states, or syncing `tasks/00-INDEX.md` |
| **Execution Modes Supported** | **Single-Framework Native** (parallel native worktrees/subagents) and **Multi-Framework MCP / CLI** |
| **Engine Access (3 Progressive Tiers)** | 1) **Plain Markdown + Git** (`tasks/AGENTS.md` + `references/template.md` — zero install, works without extension, MCP, or CLI), 2) **Standalone CLI** (`~/.local/bin/ai-orch` or stdlib-only `python3 scripts/tasks_engine.py` — no MCP or extension needed), 3) **Broker MCP tools** (`ai-orch mcp`, preferred when installed) |
| **Related Skills** | `orchestration-workflow`, `task-spec-authoring`, `orchestration-setup` |

## Reaching the task engine

The `tasks/` tree is plain, Git-tracked Markdown by design: every file (`00-INDEX.md`, `CONTEXT.md`, `AGENTS.md`, `NN-<slug>/plan.md`, `<category>/T###-<slug>.md`, `questions/Q###-<slug>.md`, `_inbox/`) is usable directly by any developer or AI assistant — even on a machine without the VS Code extension, the broker MCP server, or the `ai-orch` CLI installed. Use the highest tier available in the current environment, and never run the engine from a versioned plugin-cache path or a stale vendored copy:

1. **Tier 1 — Broker MCP tools (`ai-orch mcp`, preferred when registered):**
   - `whoami` — Report broker identity (`pid`, `version`, `started_at`) and `unread_mail`.
   - `workspaces.list` — List registered workspaces (`uuid`, `slug`, `title`, `path`, `orchestrator`, `unread_mail`), paged.
   - `projects.list` — List projects (`uuid`, `slug`, `path`, `kind`) in a `workspace`, paged.
   - `tasks.list` — Return compact, paged task rows for `workspace` and `project` (filterable by `state`, `kind`, `label`, `text`).
   - `tasks.show` — Return full details (`header`, `goal`, `steps`, `verification`, `children`, `attachments`, `hash`, `path`) for one task `(workspace, project, id)`.
   - `tasks.next` — Return actionable ready-queue tasks for `workspace` (and optional `project`), paged.
   - `tasks.graph` — Return the dependency graph (`nodes`, `edges`, `ready` queue) for `workspace` and `project`.
   - `tasks.new` — Create an emergent task in `(workspace, project)` (`title`, `short`, `goal`, optional `category`, `priority`, `priority_reason`, `kind`, `parent`, `idempotency_key`, `expect_hash`, `preview`).
   - `tasks.transition` — Transition task state in `(workspace, project, id, to)` (optional `note`, `idempotency_key`, `expect_hash`, `preview`).
   - `tasks.set` — Update a task field (`priority`, `size`, `deps`, `kind`, `labels`, `short`) on `(workspace, project, id)` (optional `idempotency_key`, `expect_hash`, `preview`).
   - `questions.list` — List blocking questions for `workspace` (and optional `project`, `status`), paged.
   - `questions.ask` — File a blocking question in `(workspace, project)` (`question`, `short`, `context`, `options`, optional `recommended`, `blocks`, `idempotency_key`, `expect_hash`, `preview`).
   - `questions.answer` — Record an answer to a blocking question `(workspace, project, id, choice)` and unblock waiting tasks (optional `text`, `idempotency_key`, `expect_hash`, `preview`).
   - `inbox.add_note` — Add an inbox note in `(workspace, project)` (`title`, `body`, optional `kind`, `idempotency_key`, `expect_hash`, `preview`).
   - `orchestrator.status` — Inspect workspace orchestrator status (`state`, `tool`, `model`, `generation`, `queue_length`, `worker`, `unread_mail`).
   - **Broker MCP conventions:**
     - **Addressing:** Every tool takes explicit `workspace` (slug or uuid) and, where it acts on a task tree, `project` (slug, or `_workspace` for the workspace-level coordination tree). Inside a project, task/question/note IDs are bare (`T###`, `NN.T`, `Q###`, `N###`).
     - **Mutations:** Every mutating tool (`tasks.new`, `tasks.transition`, `tasks.set`, `questions.ask`, `questions.answer`, `inbox.add_note`) accepts `expect_hash` (optimistic CAS against the hash from the last read), `idempotency_key` (safe retry returning the stored result), and `preview: true` (dry-run without writing), and returns the new `hash`.
     - **Paging:** List tools (`workspaces.list`, `projects.list`, `tasks.list`, `tasks.next`, `questions.list`) return compact rows with `cursor` / `next_cursor` (`limit` default 50, max 200; responses capped at 256 KiB with `truncated: true`); fetch full task bodies on demand with `tasks.show`.
     - **No nulls:** Tool arguments and responses never carry `null` fields (omitted instead of `null`).
   - **Setup:** The Environment Doctor (`ai-orch env status`) detects missing or stale broker MCP registrations across Claude Code, Kilo, and Codex and offers a preview/apply plan (`ai-orch env register-broker --assistants all --apply --expect-hash <hash>`). `ai-orch install-launcher` (`--apply --expect-hash <hash>`) writes the version-free launcher at `~/.local/bin/ai-orch` so MCP registrations (`~/.local/bin/ai-orch mcp`) survive plugin updates.
2. **Tier 2 — Standalone CLI (no MCP server and no VS Code extension required):**
   - When a session has no broker MCP tools, run the CLI through the version-free launcher path (`~/.local/bin/ai-orch tasks …`, `ai-orch questions …`, `ai-orch inbox …`), or invoke the bundled stdlib-only script (`python3 <skill-dir>/scripts/tasks_engine.py …`) when only this skill is installed.
   - For global CLI access without MCP, `ai-orch install-launcher --apply` installs `~/.local/bin/ai-orch` as the version-free entry point.
   - **Standalone Project Versioning:** `task-pipeline` (`plugins/architect-side/skills/task-pipeline/`) can be versioned directly inside any repository (`.kilo/skills/task-pipeline/` or `.claude/skills/task-pipeline/`) and works 100% standalone using only Python 3 stdlib (`python3 <skill-dir>/scripts/tasks_engine.py ...`) or pure Markdown editing (`tasks/AGENTS.md` + `references/template.md`), with no extension, no MCP server, and no `ai-orchestration` checkout required. Event emission operates completely silently when `orchestration_events` is absent.
3. **Tier 3 — Direct Markdown + Git (zero install: no extension, no MCP, and no CLI installed):**
   - When neither the VS Code extension, nor the MCP server, nor the `ai-orch` CLI is installed, read, create, transition, and close tasks directly in Markdown + Git (`git mv` to `tasks/done/<category>/`) following the format rules, header field order, section skeletons (`references/template.md`), and `00-INDEX.md` table columns documented in this skill and in `tasks/AGENTS.md`. Preserve the `<!-- ai-orch:generated ... -->` HTML comment markers in `tasks/00-INDEX.md` when updating tables by hand so later CLI/UI syncs remain lossless.
- **Citation rule:** Always cite tasks and questions as `ID (short title)`, qualified as `project/ID (short title)` across projects (see "Citing tasks and questions: id plus a short title" below).

### Format is not optional (every create or edit)

Through the broker or the CLI, the engine writes the format for you; when neither MCP nor CLI is installed (or whenever a file is touched by hand), follow these exact rules so every file remains 100% compatible with the engine and UI:

- **Plan tasks** are blocks `### NN.T - <title>` (number, space, hyphen or dash, space, title), each followed by `- **Status:** \`<state>\` · ...`. Optional status line segment or bullet `**Short:** <3-4 words>`. Never bullets (`- **T1 — ...**`), never table rows, never `T<n>` ids inside a plan (`T###` belongs to emergent tasks). Prefer children (`12.2.1`) over letter suffixes (`12.2a`), which are accepted but harder to extend.
- **Emergent tasks** are created with the broker tool `tasks.new`, `ai-orch tasks new --category C --title T [--short S] --priority P --priority-reason R --goal G [--paths ...] [--executor ...]` (or `--from-note N###` from an inbox note), or — when no tool is installed — by copying the exact header order (`id`, `title`, `category`, `priority`, `priority-reason`, `next-up`, `state`, `executor`, `depends-on`, `decider`, `sources`, `paths`, `handoff`, plus optional `short`) and required sections (`## Goal`, `## Steps`, `## Verification`) from "Where and how" below and [`references/template.md`](references/template.md).
- **After every change under `tasks/`:** when `ai-orch` or `scripts/tasks_engine.py` is available, run `ai-orch tasks validate` (zero errors and no "non-canonical task items" warning for the files you touched) and `ai-orch tasks sync-index --check` (or `--apply`). When no CLI is installed, update the matching row in `tasks/00-INDEX.md` inside the `<!-- ai-orch:generated ... -->` markers in the same commit.
  - **Worktrees, parallel branches, and the `ai-orch-index` git merge driver:** Executor worktrees should NOT commit `tasks/00-INDEX.md` when working on an isolated feature branch (the orchestrator runs `sync-index --apply` on the integration branch after merging). When parallel branches both touch `tasks/00-INDEX.md`, `tasks/.gitattributes` maps `00-INDEX.md merge=ai-orch-index` and `ai-orch tasks upgrade --apply --expect-plan-hash <hash>` registers the local git merge driver (`git config merge.ai-orch-index.driver "<stable-ai-orch> tasks merge-index %O %A %B"` and `git config merge.ai-orch-index.name "ai-orch conflict-free 00-INDEX.md merge driver"`, using `~/.local/bin/ai-orch` if installed else the checkout's `bin/ai-orch`). `ai-orch tasks validate` warns if `.gitattributes` names `merge=ai-orch-index` but git config lacks the driver. During `git merge`, `tasks merge-index %O %A %B` performs a row-level 3-way merge across generated tables (union of rows keyed by task ID minus deletions relative to base; conflicting edits of the same row regenerated from disk headers if present else keeping theirs) and a standard 3-way text merge outside generated regions. If `00-INDEX.md` ever conflicts manually, `ai-orch tasks sync-index --apply` (or `ai-orch tasks merge-index`) resolves it deterministically.
- **State follows the work:** assigning a task moves it to `in progress` before the executor starts, the executor's commit + Final Report moves it to `delivered`, and so on — through the engine (`tasks.transition` or `ai-orch tasks transition <id> <state>`) when available, or by updating `- state:` (and `- **Status:** \`<state>\`` in `plan.md`) plus `tasks/00-INDEX.md` directly when working in plain Markdown. See `orchestration-workflow`, "Track task state as a path".
- **Found a project in an older format?** Follow "Normalizing existing tasks" below before adding to it.

## Purpose

Produce a durable, resumable home for development work too large for one
sitting or one agent invocation - refactors, feature rollouts, anything meant
to be picked up across sessions or delegated one piece at a time. The format
survives context loss: a fresh session or a delegated agent with zero
conversational memory must read the files and continue correctly, without
re-deriving decisions already made or silently re-answering a resolved
ambiguity.

It models the whole flow, not just the plan: **raw input → structured spec →
initiative plan → completion summary**. Raw notes and transcripts are
first-class (they arrive before anyone knows which initiative they feed), specs
are first-class (one spec can drive several initiatives), and completion is
visible at the folder level.

## When to use

- The work has multiple dependent or independent pieces, each big enough to
  need its own verification step.
- It will span more than one session, or be picked up by a different agent
  instance (fresh Claude session, or Kilo) with no memory of the design
  conversation.
- Real design ambiguities were resolved through back-and-forth with the user
  that must not be re-litigated or silently re-decided later.
- You have raw material (notes, call transcripts, dumps) to turn into specs and
  tasks.
- **A new piece of work emerges mid-conversation** (a request aside from the
  current one, a finding, a follow-up, a decision waiting on someone). Capture
  it as an emergent task - see "Emergent tasks" below. This applies even when
  you will do it yourself.

Do not force this onto a single small change one agent finishes and verifies in
one pass - that's a normal plan. The ceremony pays off only at scale.

## Structure

```text
task/
  AGENTS.md          the convention (a copy of this skill's rules, so the repo
                     is self-contained for agents/teammates without the skill)
  CONTEXT.md         SHARED context - durable, project-wide facts read first:
                     codebase map, command/API surface, cross-cutting locked-in
                     decisions & conventions every initiative relies on
  00-INDEX.md        live REGISTRY - every initiative, its priority, its status,
                     and the spec→initiative map
  _inbox/            RAW input - no structure rules; split by analysis state:
    to-analyze/        not yet analyzed (the "hand off for analysis" queue)
    analyzed/          already distilled into specs/tasks (kept for provenance)
  specs/             structured specs; each may drive ONE or MANY initiatives
    <slug>.md
  questions/         BLOCKING questions waiting on decider (Q###-<slug>.md)
  NN-<slug>/         an ACTIVE initiative
    plan.md            task breakdown; tasks NN.T, each sized for one commit
    NN.T-<name>.md     (only when expanded - see "Task packaging" below)
    summary.md         completion record (added when the initiative ships)
  <category>/        EMERGENT tasks, grouped by kind of work (see "Emergent tasks")
    README.md          goal, scope, owner session, start prompt, shared notes
    notes/             the category's working notes
    T###-<slug>.md     a small task
    T###-<slug>/       a task with context: README.md, CONTEXT.md, PROGRESS.md
  done/              COMPLETE on a branch, awaiting merge (moved here unchanged)
    NN-<slug>/
    <category>/        finished emergent tasks (same names)
  merged/            MERGED into the integration branch (final)
    NN-<slug>/
```

Three terminal states, folder-visible (name/id preserved, only the path prefix
changes): **active** (`tasks/NN-<slug>/`) → **`done/`** (implemented + verified on
its branch, `summary.md` written, not yet merged) → **`merged/`** (branch merged
into the integration branch, e.g. `development`). Completion delegated to
another agent lands in `done/`; the orchestrator promotes it to `merged/` after
merging.

Three top-level docs, deliberately split by what changes and when - read
top-down, stop when you have enough:

- **`AGENTS.md`** - *how the system works* (this convention). Stable across
  projects; rarely changes.
- **`CONTEXT.md`** - *what this project is*. Durable project-wide grounding:
  file layout, the real command/API/data surface (annotated with which
  initiative added what), and cross-cutting **locked-in decisions** that span
  initiatives. Evolves as the codebase does; explicitly marked as needing
  re-verification against the real files, since it drifts between sessions.
- **`00-INDEX.md`** - *current state*. The registry of initiatives with a
  Priority column (priority ≠ the stable `NN` id), a Status column, the
  spec→initiative map, and the **task queue** (one line per emergent task, the
  next-up list on top). This is the "what's left / what's done" source of truth.

Copy-paste skeletons for every file kind are in
[`references/template.md`](references/template.md).

## The pipeline: raw → spec → plan → summary

1. **Capture.** Drop unstructured material into `_inbox/to-analyze/`. Either as a
   plain Markdown file (e.g. `2026-07-20-call-luca.md`) or as a structured note
   folder `_inbox/to-analyze/<YYYYMMDD-HHMMSS>-<slug>/` containing `note.md`
   (with `N###` header) and optional `attachments/` (images, PDFs, text files; up
   to 10 MB per file, max 30 attachments). Plain `.md` notes remain valid and
   convert to folder form on first edit or attachment.
2. **Analyze.** Distil it into one or more `specs/<slug>.md`. The spec is the
   *what & why* and becomes the source of truth for implementation - not the
   raw note. Move the processed raw file to `_inbox/analyzed/`, noting which
   spec(s)/initiative(s) it produced.
3. **Plan.** Each spec **generates new** initiatives or **updates/restructures
   existing** ones. `NN-<slug>/plan.md` is the *how*.
4. **Ship.** On completion, run `ai-orch tasks ship NN` (preview with `--dry-run`,
   apply with `--expect-plan-hash <hash>`). This creates `NN-<slug>/summary.md` skeleton,
   moves the folder into `tasks/done/`, and automatically rewrites references in
   specs and `00-INDEX.md`.

## Emergent tasks: capture work the moment it appears

Work rarely arrives only through planning. Mid-conversation, the user asks for
something aside from the current task, a review turns up a defect out of scope,
a "next step" comes up, a decision waits on someone, a peer session hands
something over. If that work lives only in the conversation, it is lost when
the session ends or is compacted, nobody else can pick it up, and it keeps
occupying the session's context while it waits.

**Rule: capture first, then continue — following the use-case-first workflow.**
As soon as new work appears and will not be finished and verified in the current
turn, write it down, then go back to what you were doing. In the reply, cite the
task by id and path. A "next steps" paragraph in the chat is not a substitute.

For any new `feature` or `fix` request, capture follows the **use-case-first** steps
(skipping directly to tasks is allowed for `chore`, `docs`, and `investigation`):
1. **Find related use cases:** Run `ai-orch tasks use-cases search <text> [--actor A] [--json]` (matches text in title/description/scenario/criteria, actor, cited specs `Source: tasks/specs/...`, and use cases linked to tasks touching the same `paths` or `sources`).
2. **Reconcile or draft:** Propose updates to matching use cases, or point out contradictions between the request and existing use cases (scenario, acceptance criteria, scope), and/or draft missing use cases (`ai-orch tasks use-cases create ...`, written with `approval: proposed`).
3. **Get approval:** Get the new or updated use cases approved by the user/decider (`approval: approved`) — file a blocking question (`Q###` via `questions.ask` / `ai-orch questions ask`) when the user is not in the conversation.
4. **Write specs and create linked tasks:** Only after use-case alignment, write or update `specs/<slug>.md` and create the tasks linked to their use cases (`--use-case UC###[,UC###]` or `--from-use-case UC### [--steps M-N]` to pre-fill title, `## Goal`, and `## Verification`).

### Where and how

- **Initiative or emergent task.** If the work belongs to an existing
  initiative, add it to that plan as a task `NN.T`. Otherwise it is an
  emergent task in `tasks/<category>/`. A task that grows into several
  dependent pieces is promoted to an initiative; its `T###` id stays in the
  initiative's `Derived from`.
- **Id.** `T###`, unique across the whole tree including `done/`, never reused.
  Take the highest existing id plus one. Reserve it by creating the file at
  once, and re-check right before creating it: parallel sessions create tasks
  in the same repository at the same time, and id collisions do happen.
- **Shape.** A small task is one file, `T###-<slug>.md`. A task with context or
  progress worth keeping is a folder, `T###-<slug>/`, so that the definition,
  context, progress and evidence live in the task and not in a session:
  - `README.md`: the definition (header, goal, steps, verification);
  - `CONTEXT.md`: everything needed to resume without the original session:
    where the work is, how to build and check it, rules the user gave, facts
    already established (each with the command or file that established it).
    Write it while the context is still fresh: that is its point;
  - `PROGRESS.md`: a log, newest first, and the checklist of open items.
    Update it in the same change as any work on the task;
  - `attachments/`: evidence and supporting files (images, PDFs, text files; up to
    10 MB each, max 30 files), added with `ai-orch tasks attach` and detached
    with `ai-orch tasks detach`. Attaching to a single-file task automatically
    promotes it to folder form (`cat/T###-slug/README.md`) byte-identically.
  Converting an inbox note via `ai-orch tasks new --from-note` preserves evidence
  by copying note attachments into the new task folder and rewriting links.
  A file is promoted to a folder, with the same id, when it gets progress worth
  keeping or receives attachments.
- **Header.** One `key: value` line per field, so the headers can be grepped.
  The set is **closed** and the order is the one below, always all fields
  present; an empty value is `-` (never omit a line):
  - `id`, `title`, `category`;
  - `priority` (P0–P3) and `priority-reason` (one line);
  - `next-up`: `yes` or `no` (default `no`);
  - `state`, `executor`;
  - `depends-on`: task ids, or `-`;
  - `decider`: `Q###` (or comma-separated `Q###` list) when blocked by questions, else `-` (legacy free-text `owner: <question>` remains valid);
  - `sources`: where it emerged (conversation date, file, finding, raw row id);
  - `paths`: the repositories and paths the task touches;
  - `handoff`: the one-line prompt that starts a fresh session or agent on the
    task: what to read, what to do and what to update. Name the task by its own
    path (`tasks/<category>/T###-<slug>.md`, or `.../T###-<slug>/README.md` for
    a folder task) and say "the registry" instead of hard-coding the index
    path, so it survives a move of the index.

  **Optional Orchestration Extension Fields (placed immediately after `handoff` in canonical order):**
  A project using `ai-orchestration` may include these optional fields
  immediately after `handoff`:
  - `profile`: `deep-reasoning` | `orchestration` | `bulk-execution` | `exploration`
    (selects the model/variant from `orchestration.toml` for the chosen `executor`,
    whether dispatched natively in the same framework or via MCP);
  - `verification-mode`: `self` | `independent-session` | `cross-agent` | `panel` | `owner`
    (overrides `[verification].default_mode` in `orchestration.toml`:
    `independent-session` uses a fresh context-blind subagent in the same
    framework; `cross-agent` uses a different framework/engine; `panel` runs
    multiple reviewers; `owner` requires human approval);
  - `verifier`: `-` | `<tool>:<profile>` | `blind-subagent:<profile>` | `owner` | `panel(...)`
    (records who is assigned or performed the independent verification);
  - `verify-by`: `<workspace-or-session>`
    (records a durable verification request addressed to another workspace or session,
    e.g. `gcube_atlas`, `workspace:gcube_atlas`, `session:kilo-...`);
  - `size`: `XS` | `S` | `M` | `L` | `XL` (relative weight; defaults to M for full tasks, XS for microtasks);
  - `kind`: `feature` | `bug` | `fix` | `chore` | `docs` | `investigation` (classification kind; required for microtasks, optional for full tasks);
  - `labels`: free tags matching `[a-z0-9][a-z0-9-]*` (max 24 chars each, comma-separated, e.g. `ui, security`);
  - `branch`, `worktree`, `run-id`, `use-cases`;
  - `short`: `1–5 words, ≤40 chars, no trailing punctuation` (a concise 3-4 word label stored with the item and used whenever cited; see [Citing tasks and questions: id plus a short title](#citing-tasks-and-questions-id-plus-a-short-title)).

  **Microtask Form (`tasks/micro/T###-<slug>.md`):**
  A lightweight emergent task for very small work (bug, fix, chore, docs touch-up) that shares the same ID space (`T###`), state machine, and dependency semantics:
  - **Header (closed set, exact order):** `id`, `title`, `kind`, `priority`, `state`, `executor`, `paths`, `depends-on`, `size`, `labels`, `short` (optional).
  - **Body:** one required section, `## What`. No `Goal`/`Steps`/`Verification` skeleton needed.
  - **Size:** defaults to `XS`.
  - **Commands:** `ai-orch tasks micro --title ... [--short ...] [--kind ...] [--priority ...] [--label ...]` creates a microtask under the task-write lock; `ai-orch tasks promote <id> [--category <cat>]` promotes it to a full task in a chosen category.

  **Per-project extension fields:**
  A project may declare additional allowed header fields (placed after `handoff`, e.g. `area`) via `[tasks] extension_fields = ["area"]` in its `orchestration.toml` (or `.ai-orchestration.local.toml`), via a fenced `toml` block in `tasks/AGENTS.md`, or via a prose/bullet line in `tasks/AGENTS.md` (e.g. ``Extra header fields: `area` `` or ``- **Extra header fields: `area`, `subdomain` and `component`**``):
  ```toml
  [tasks]
  extension_fields = ["area"]
  ```
  Undeclared extra fields are rejected by `tasks validate`; put other information in the
  body. Then the required sections `## Goal`, `## Steps` and `## Verification`.
  While the state is `delivered`, a line `verification pending: <what is left to
  check, and by whom>` goes right after the header (when `verify-by` is set:
  `verification pending: <what-to-check or 'run Verification checks'> (verify-by: <target>)`).

  **Per-project content languages & fixed English keywords:**
  Section headings (`## Goal`, `## Steps`, `## Verification`, `## Log`; question `## Context`, `## Options`, `## Answer`, `## Notes`; use-case `## Description & Business Value`, `## Preconditions`, `## Scenario / Interaction Steps`, `## Automated Verification Command`, `## Acceptance Criteria`, `## AI Validation Log`) and header field names are a formal **English vocabulary** of the format and are never translated.
  A project declares the language for the **prose content** written by sessions in a fenced `toml` block in `tasks/AGENTS.md` (versioned with `tasks/`):
  ```toml
  [tasks]
  language = "it"

  [questions]
  language = "en"

  [use_cases]
  language = "it"
  ```
  - `[use_cases] language` defaults to `[tasks] language` when omitted; overall default is `"en"`.
  - `tasks upgrade` writes the effective content languages and the fixed-English-keywords rule into the managed block of `tasks/AGENTS.md`.
  - `ai-orch tasks config` (or `show-config`) reports the effective languages and their sources.

### States

`open`, `in progress`, `waiting` (on a blocking question `decider: Q###` or external party),
`blocked` (on an unresolved upstream task or dependency), `delivered`,
`bounced` (verification failed; returns to the same executor session with
findings `B1..Bn` recorded in `PROGRESS.md`), `verified`, `done` (or `done with
a caveat`: name the caveat), `dropped` (say why).

- **No direct `open → done` or `in progress → done`:** every implementation
  task must pass through `delivered`.
- `delivered` means the executor finished, committed, and checked its own work.
  Nobody else has checked it yet.
- **`bounced`** means an independent verification check failed; the failing
  criterion (`B1..Bn`) is appended to `PROGRESS.md` and sent back to the same
  executor session (`bounced → in progress`).
- **`verified`** is set by someone other than the executor (a fresh blind
  subagent in `independent-session` mode, another engine in `cross-agent` /
  `panel` mode, the orchestrator, or the user) after re-running the
  Verification, **or by the executor once the user has explicitly approved the
  result in conversation**: the user's approval counts as verification. Record
  it in `PROGRESS.md` (date and what was approved). Without one of the two, the
  executor does not set `verified`.
- **`done`** is set by whoever closes the task, once the Verification has been
  run. The normal path is `delivered` → `verified` → `done`. When nobody else
  is available to verify (`verification-mode: self`), the executor may close it
  as `done with a caveat: self-verified only` (and `PROGRESS.md` records the
  self-check); it does not set `verified` on its own authority. A task that
  waits for someone else's check or for the user's approval stays `delivered`.

### Durable verification requests and the verification queue

When an executor completes a task whose verification must be performed by a different workspace or session:
- **Set `verify-by` on delivery:**
  ```sh
  ai-orch tasks transition <id> delivered --verify-by <workspace-or-session> [--verify-check "what to check"]
  ```
  or set/update it explicitly:
  ```sh
  ai-orch tasks set-verify-by <id> <target> [--check "what to check"]
  # or alias:
  ai-orch tasks request-verification <id> --by <target> [--check "what to check"]
  ```
- **Task file & 00-INDEX.md updates:**
  - Header: `- verify-by: <target>` (or `**Verify-by:** <target>` in inline plan task metadata).
  - Body: `verification pending: <check> (verify-by: <target>)`.
  - In `00-INDEX.md`: the State column displays `delivered (verify-by: <target>)`.
- **Draining verification queue at session start:**
  Every session must check and drain its verification queue at session start:
  ```sh
  ai-orch tasks verification-queue --for <workspace-slug> [--json]
  ```
  For each delivered task addressed to the workspace:
  1. Re-run the task's `Verification` checks from its task file.
  2. If all checks pass, transition the task to `verified`:
     ```sh
     ai-orch tasks transition <id> verified --verifier <workspace-slug> --reason "OK: <details>"
     ```
  3. If verification fails, bounce it back to the executor:
     ```sh
     ai-orch tasks transition <id> bounced --reason "NOT OK: <details>"
     ```
- Transitioning the task to `verified`, `done`, `done with a caveat`, `bounced`, or `dropped` automatically clears the pending verification request so the task is no longer pending in the verification queue.

### Executor-agnostic

The `executor` value is one of:
- `self`: the session that captured the task does it, itself;
- the agent's product name (`kilo`, `claude`, `codex`, ...) for a delegated
  agent, including a subagent or an MCP-delegated run started by the capturing
  session; the model goes in `PROGRESS.md`, not in the header;
- `dedicated-session`: a session started for this task;
- a person's name, or `user-decision` when the task is a decision.

The lifecycle is the same for all of them. A task you do yourself still moves
through its states, and is not done until its Verification has been run.
Writing it down is what lets it change hands later.

### The registry: `tasks/00-INDEX.md`

The single dashboard of the tree, next to the tasks. Next to the initiatives
table it holds:
- **next-up**: at most five tasks, each with its handoff prompt;
- **one table per category**, sorted by priority then id: id, priority, title
  (linked to the task file or its `README.md`), state, executor, depends-on;
- **decisions waiting**: open questions rendered from `tasks/questions/` (key,
  short question, blocked tasks, decider, recommendation);
- **done**: closed tasks, newest first, with their result (`done`,
  `done with a caveat`, `dropped`).

**Update the task and the registry in the same change**, every time. The task
header is the source of truth for `state`, `priority`, `executor`, `depends-on`
and `decider`; the registry rows (and the decisions-waiting table, which
repeats `decider`) are derived from it. On a mismatch, the header wins and the
registry is fixed. A registry may add a column for who must act or give access
(e.g. `Owner`).

**Done.** `tasks/done/<category>/` is the final place of an emergent task
(`done`, `done with a caveat` or `dropped`): there is no `merged/` step for
emergent tasks (that one belongs to initiatives, see Structure). When the task
is closed, update `PROGRESS.md`, move the task with
`git mv` to `tasks/done/<category>/` (same name), and update the registry, in
one change. Then check the Markdown links: a move breaks relative links in
both directions, and every link in `tasks/` must still resolve.

### Categories and priority

Recommended when more than one session works on the queue; optional otherwise.

- **Categories** are kinds of work chosen per project (e.g. `porting/`,
  `maintenance/`, `release/`, `decisions/`). Create one only when no existing
  one fits. `tasks/done/<category>/` mirrors them. Each category has:
  - a `README.md`: the goal and scope of the category, the `owner-session`, the
    rules, a **start prompt** for a session that takes over the whole category,
    and "Shared notes";
  - a `notes/` folder for its working notes.
- **Priority** always carries a written reason:
  - **P0**: security exposure, or it blocks a release in progress or many tasks;
  - **P1**: needed for the project goal;
  - **P2**: important, off the critical path;
  - **P3**: nice to have.

### Keep the context clean

Capturing a task moves it out of the session's working memory. The session
keeps only its one-line registry entry, not the details. Read a task's files
only when you pick it up. When someone else will execute it, the task is the
whole hand-off: a fresh session or agent starts with an empty context and the
task files.

### Project-local tasks inside a workspace

A workspace often contains projects with their own repository, worktree or
folder (a documentation site, a library, a proposal). Work that is **strictly
about one project** is kept in that project, not in the workspace tree:

- **Project tree.** The project has its own `tasks/` (`00-INDEX.md`, a shared
  `CONTEXT.md`, categories, `done/`), with the same conventions as this skill
  and its own `T###` ids. It travels with the project: when the project is
  moved, shared or handed to someone else, its tasks, context and progress go
  with it and nothing load-bearing stays in the workspace.
- **Pseudo-task in the workspace.** The workspace `tasks/` keeps one task per
  project (or per significant project task) that only **points** to the project
  tree and mirrors its state, so that "what do we have to do?" is answered from
  the workspace registry alone. Its body has: the path of the project tasks
  folder (relative, or the name of the repository if it will live elsewhere),
  the current state of the project tasks (ids and states, one line each), who
  must act, and the next step. It carries no context and no progress log: those
  live in the project.
- **Single source of truth.** The project task header owns `state`, `priority`,
  `executor`, `depends-on` and `decider`. The pseudo-task and its registry row
  are derived: when a project task changes state, update the pseudo-task in the
  same change (or, if the project is outside the workspace repository, at the
  next time the workspace registry is touched, saying so in `PROGRESS.md`).
- **Paths and ids.** A pseudo-task is a normal workspace task (own `T###`,
  category, priority with a reason, `paths` = the project tasks folder). Never
  reuse a project id in the workspace or the reverse; cite project tasks as
  `<project>/T### (short title)`.
- **Moving a project out.** When a project leaves the workspace, move its tasks
  with it, update the pseudo-task's pointer, and keep the pseudo-task until the
  workspace no longer needs to track the project.
- **Not for cross-cutting work.** Work that touches several projects, or the
  workspace itself, stays a normal workspace task.

### Several sessions on one repository

- The state of a task is in its file or folder, never in conversation memory.
  A session that stops leaves its tasks current.
- Only a category's owner session edits that category's task files and
  `README.md`. Other sessions add dated notes under "Shared notes", or create
  new `T###` tasks.
- **Orchestrator registration & heartbeat:** When orchestrating with `ai-orch` installed,
  register the session with `ai-orch sessions register --role orchestrator` and heartbeat
  periodically (`ai-orch sessions heartbeat <session_id>`). Interactive sessions (e.g. Claude Code)
  do not send heartbeats automatically: emit a heartbeat on each turn or periodic check;
  a "stale" interactive holder reflects idle time, not absence.
- Re-check facts with git before acting on a task file: other sessions edit the
  repository too.
- **Validation round.** When the queue is built in bulk from documents (notes,
  old hand-offs, a sweep of a repository), its states and dependencies are
  guesses. Ask each session that holds live knowledge of an area to confirm or
  correct the tasks of that area before anyone works from the queue. Each
  session reports the corrections in its own task files. Keep the raw material
  the queue came from, and cite its row ids in `sources`.

**Never in a task file:** secrets, tokens, personal data, or details of
undisclosed vulnerabilities. Point to where they are kept instead. A claim
that something does not exist cites the command that searched for it.

## Citing tasks and questions: id plus a short title

The owner cannot map bare ids to work. Whenever you mention a task, plan task,
initiative, use case or question in chat, in a summary, in a Final Report or in
a question's text, write the id followed by a 3-4 word short title in
parentheses: `T007 (shared release manager)`, `12.16 (UI proposal confirm)`,
`Q007 (security-audit release)`. Across projects, qualify the id as
`project/ID (short title)` (and across workspaces as `workspace:project/ID (short title)`).
Never use a bare id, tables included (add a short-title column or put the title
next to the id).

- Take the short title from the task's `Short:` / `short:` field when it exists;
  otherwise derive 3-4 words from its full title (keep them stable within a session).
- When you create a task or question, give it a short title as well, so every
  agent cites it the same way.

## Blocking questions (`tasks/questions/Q###-<slug>.md`)

When an agent hits a decision that belongs to the owner or decider (scope changes,
security trade-offs, financial cost, irreversible actions, conflicting requirements),
never guess or decide silently. File a blocking question instead of stalling or
assuming.

- **File format & rules:** See `tasks/specs/blocking-questions.md`. One file per
  question in `tasks/questions/Q###-<slug>.md`. `Q###` is unique across the tree.
  - `question`: standalone sentence, ≤160 chars, ending with `?`. Must make sense
    without reading anything else (no "this", "the above").
  - `## Context`: self-sufficient facts and stakes so the decider can decide from
    the card alone.
  - `## Options`: ≥2 labelled options (`- **A** — <label>: <consequence>`), or
    empty if pure open question with `open-answer: yes`.
  - `recommended`: recommended option label (e.g. `A`), or `-`.
  - `open-answer`: `yes` or `no`.
- **Minimal complete example:**
  ```markdown
  # Q002 Permission policy for headless runs

  - id: Q002
  - question: Which permission policy should headless runs use by default?
  - status: open
  - blocks: T013 (in progress)
  - decider: owner
  - asked-by: claude:orchestration
  - asked: 2026-10-17
  - origin-run: -
  - open-answer: yes
  - recommended: A

  ## Context
  Headless runs cannot prompt. Tools outside allow-list are denied.

  ## Options
  - **A** — Per-mode allow-list: safe default, stalls logged.
  - **B** — Broad allow-list: never stalls, grants full shell access.

  ## Answer
  - choice: -
  - answered-by: -
  - answered: -

  ## Notes
  Optional free-form notes, discussion, background links, or analysis.
  ```
- **Task linkage:** Asking moves the blocked task to `waiting` with `decider: Q###`
  (recording prior state). When answered, withdrawn, or moved, the task is restored to its
  prior state and `decider: -`.
  - **Non-blocking questions:** Pass `--blocks -` (or omit `--blocks`) to file a question without
    blocking any task (e.g. general architecture decisions or decisions gating an initiative).
  - Legacy free-text `decider: owner: <question>` remains valid; convert with `ai-orch questions ask --from-task T###`.
- **Engine commands (`ai-orch questions`):**
  - `ai-orch questions ask --question "..." --context "..." --option "A=..." [--blocks T###|-] [--notes "..."]`
  - `ai-orch questions answer Q### --choice A [--text "..."] [--apply-ref <ref>] [--note "..."]`
  - `ai-orch questions apply Q### --note "..."` (records application in ledger and marks `applied: yes`)
  - `ai-orch questions move Q### --to <url-or-ref> [--reason "..."]` (status `moved`, unblocks tasks, archives under `questions/answered/`)
  - `ai-orch questions withdraw Q### --reason "..."`
  - `ai-orch questions list [--status open|answered|withdrawn|moved|unapplied|all]` (notices unapplied answers)
  - `ai-orch questions show Q###`

## Task packaging: one file, or one file per task (by size)

`plan.md` always exists. The tasks inside can be packaged two ways - pick by
size; the logical granularity is identical either way (**one task `NN.T` = one
independently-verifiable unit = one commit**):

- **Inline (default).** Small/medium initiative: tasks `NN.T` are sections
  inside the single `plan.md`. Compact, read in one pass.
- **Expanded (large / delegated).** Each task `NN.T` becomes its own
  `NN.T-<name>.md` file; `plan.md` becomes the initiative index (goal, shared
  decisions, links to each task file). Use this when tasks exceed ~5-6, when a
  single task's grounding/steps/verification is too big to sit inline, or when
  tasks will be delegated one-by-one to separate agents/worktrees (one file =
  one task = one hand-off = one commit).

Converting inline → expanded (or back) is cheap; do it when an initiative
grows. Whichever form, keep each task's **Verification** section with it.

## Core principles

- **Ground everything in real code, not descriptions of it.** Before writing a
  spec or task, grep/read the actual files and quote them. "Tags follow
  `r<major>.<minor>.<patch>`" is trustworthy only once checked against real
  tags - wrong grounding is exactly what sends a delegated agent down the wrong
  path with total confidence.
- **Locked-in decisions are durable memory for resolved ambiguities.** Every
  real design fork resolved via a clarifying question becomes one bullet: the
  decision, then *why* (the trade-off/constraint that drove it). Cross-cutting
  ones live in `CONTEXT.md`; spec-specific ones in that `spec.md`. A fresh
  agent must never re-derive or re-guess what a human already decided. If a
  question is still open, say so and flag which task must resolve it before
  starting - never silently pick.
- **Spec↔initiative is many-to-many.** Specs live in `specs/`, never inside an
  initiative folder, because one spec can drive several initiatives and one
  initiative can draw on several specs. Every spec lists what it **Drives**;
  every `plan.md` lists what it is **Derived from**. Keep those links current.
- **Explicit non-goals prevent silent scope creep.** State what a spec/initiative
  does *not* do and why. Without this, a delegated agent with less context will
  "helpfully" build the excluded thing.
- **Dependency ordering is explicit, not implied by file order.** Every
  initiative states what it depends on and why (which function/table/module it
  reuses), so independents can run in parallel and dependents are never started
  early. The `NN` number is a **stable id**, not a priority - reprioritizing
  changes the Priority column in `00-INDEX.md`, never the folder numbers.
- **Verification is part of the spec, not an afterthought.** Every task ends
  with concrete, runnable checks. "Done" must be objectively checkable, and
  it's exactly what makes a task safe to hand to another agent.
- **Task granularity = one independently-verifiable unit.** Split an initiative
  into as many tasks as it has verification checkpoints - typically 2-6.
  Don't split finer (interdependent sub-steps stay inline in one task) or
  bundle unrelated checkpoints.
- **Progressive disclosure everywhere.** Convention in `AGENTS.md`; shared
  project facts in `CONTEXT.md` once; live state in `00-INDEX.md`; the *what/why*
  in a spec; only the steps to execute in a task. A reader stops once they have
  enough. Never repeat shared-context content inside a spec or task. Apply the
  same principle when formalizing any agent instructions in a versioned repo:
  brief pointer at the top level, detail in a scoped file close to what it
  governs.
- **Numbering is stable; completion is visible.** `NN` ids never get reused or
  renumbered once work starts - append. A shipped initiative moves to `done/`
  unchanged (id preserved, only a `done/` path prefix added), so `tasks/`'s
  listing separates active vs done at a glance.

## Workflow to produce/extend one

1. Explore the real code/data (grep, read, read-only checks) - never draft a
   "Locked-in decisions" section from assumption.
2. On a genuine design fork, ask the user a concrete question grounded in what
   you found (concrete options + trade-offs, recommended-first, preview
   snippets showing each option's real consequence) - not an abstract "how
   should X work?".
3. Ensure `CONTEXT.md` carries any new cross-cutting fact/decision; create it if
   the project has none yet.
4. Write/extend the `specs/<slug>.md`, then the initiative's `plan.md`
   (inline or expanded per size), following `references/template.md`.
5. Before treating a non-trivial spec/plan as final, if other independent
   AI engines are available in the session (other MCP connectors, CLI
   tools, agents), submit it to them for review and converge on any
   disagreements rather than finalizing from one engine's judgment alone
   - a fresh, context-blind subagent instance of yourself counts too,
   since the bias removed is authorship bias, not model identity - see
   `task-spec-authoring` for the full rationale.
6. Register/refresh the initiative row in `00-INDEX.md` (priority, status,
   spec map). Keep Status current - it is the source of truth for "what's left"
   when picking up cold.
7. When a project first adopts this, drop a `tasks/AGENTS.md` capturing this
   convention so the repo is self-contained for agents/teammates who don't have
   this skill.

## Delegating a task to another agent

A task is the right unit to hand to a delegated Executor session (whether a
native worktree/subagent in Single-Framework Mode or an external MCP/CLI
Executor in Multi-Framework Mode): scoped, self-contained, with its own
objective verification. Prefer the **expanded** packaging for heavy delegation
(one task file per hand-off). When delegating:

- Point the agent at that **one** task (the `NN.T` section, its
  `NN.T-<name>.md` file, or `tasks/<category>/T###-<slug>.md`), plus the owning
  `spec.md` (for **Locked-in decisions** it must not contradict) and
  `CONTEXT.md` (global facts) - not the whole `tasks/` tree, to keep its
  context tight.
- After its report, verify against that task's own **Verification** section
  specifically (not a vibe check), then transition its state and update
  `00-INDEX.md` via `scripts/tasks_engine.py`.
- If the delegated agent's environment isn't isolated (no dedicated worktree),
  treat concurrent-writer races as a real risk, not a formality.

See `task-spec-authoring` (in `ai-orchestration`) for writing the *content*
of individual tasks and calibrating verification depth.

## Use Cases (`tasks/use-cases/UC###-<slug>.md`)

Use Cases represent end-to-end capabilities from the user/actor perspective. They drive tasks (`many-to-many`, with the task header `- use-cases:` or initiative block `**Use cases:**` as the single source of truth and `- linked-tasks:` on the use case derived automatically by `sync-index`):

### Use-case-first workflow (when a user asks for a new feature or task)

1. **Find related use cases:** Run `ai-orch tasks use-cases search <text> [--actor A] [--json]`, which ranks use cases by text match in title/description/scenario/criteria (case-insensitive, all words), actor match, cited specs (`Source: tasks/specs/...`), and use cases linked to tasks whose `paths` or `sources` overlap the query terms.
2. **Propose updates or draft missing use cases:** Propose updates to matching use cases, or point out contradictions between the request and existing use cases (scenario, acceptance criteria, scope), and/or draft missing use cases with `approval: proposed` (`ai-orch tasks use-cases create --title ...`).
3. **Get approval:** Get the new or updated use cases approved by the user/decider (`approval: approved`) — file a blocking question (`Q###` via `questions.ask` / `ai-orch questions ask`) when the user is not in the conversation.
4. **Write specs and create linked tasks:** Only after use-case approval, write or update `specs/<slug>.md` and create the tasks (`ai-orch tasks new` or `ai-orch tasks child add`), linking each with `--use-case UC###[,UC###]` or `--from-use-case UC### [--steps M-N]` (which pre-fills title, `## Goal`, and `## Verification` from the use case).
- **Skipping allowed for non-feature/fix work:** Skipping directly to tasks without a use case is allowed for `chore`, `docs`, and `investigation` (`--kind chore|docs|investigation`).

### Lifecycle: Approval vs Derived Stage

A use case separates persisted author/owner intent (`approval`) from live execution progress (`stage`):

| Field | Nature | Values | Rule / Derivation |
| :--- | :--- | :--- | :--- |
| `approval` | Persisted header | `proposed` \| `approved` \| `deprecated` | Author/owner intent. Set to `proposed` on creation; owner/decider approves (`approved`) or retires (`deprecated`). Replaces legacy `status`. |
| `stage` | Engine-derived | `draft` | No linked tasks (or all linked tasks are `dropped`). |
| | (never hand-set) | `planned` | Linked tasks exist, but none started (all `open`, `waiting`, `blocked`, `paused`). |
| | | `in development` | Work started: at least one linked task in progress, delivered, or later, but not all delivered. |
| | | `ready` | All linked non-dropped tasks delivered, verified, or done (at least one non-dropped task). |
| | | `verified` | Stage is `ready` + `last-verdict: pass` + no pending revalidation. |
| | | `failing` | Stage is `ready` + `last-verdict: fail` + no pending revalidation. |
| | | `partial` | Stage is `ready` + `last-verdict: partial` + no pending revalidation. |
| | | `untested` | Stage is `ready` + `last-verdict: untested` (or unprobed) + no pending revalidation. |
| | | `ready (revalidation pending)` | Stage is `ready` + `revalidation: pending` (a task was redelivered, bounced, or reopened). |

Use `ai-orch tasks use-cases approve|deprecate|propose [UC###[,UC###...]] [--stage <stage>] [--approval <current>] [--all] [--reason TEXT] [--by NAME]` (preview by default; `--apply --expect-plan-hash <hash>` writes) to transition `approval` individually or in bulk. Approving performs a targeted header edit setting `approval: approved`, `approved-by: <by>`, and `approved: <YYYY-MM-DD>` right after `approval` (removed on `deprecate`/`propose`), snapshots touched files under `tasks/_reviews/approval-<timestamp>/`, and emits `use_case.approval_changed` without modifying `stage` or the validation log.

### Link Rules (Many-to-Many, Task as Source of Truth)

1. **Source of Truth:** The task owns the link relation:
   - Emergent tasks: `- use-cases: UC001, UC004` (canonical header order: after `run-id`, before `short`).
   - Initiative blocks: `**Use cases:** UC001, UC004` (canonical status-line order: immediately after `**Depends on:**`).
2. **Derived on Use Case:** `- linked-tasks:` in `tasks/use-cases/UC###.md` is derived and synchronized automatically by `sync-index` and link commands. Manual edits are overwritten on sync (and flagged as warnings by `tasks validate`).
3. **Creation & Linking:**
   - Create with links: `ai-orch tasks new --use-case UC001,UC004 ...` or `tasks child add <parent> --use-case ...`.
   - Pre-fill from use case: `ai-orch tasks new --from-use-case UC001 [--steps 1-3]` pre-fills title, `## Goal`, and `## Verification` from the use case.
   - Mutate links: `ai-orch tasks link <task_id> <UC###>` and `ai-orch tasks unlink <task_id> <UC###>` (preview by default; write with `--apply --expect-plan-hash`).
4. **Migration:** `ai-orch tasks use-cases adopt-links [--expand-initiatives]` copies legacy written `linked-tasks` onto tasks before flipping the direction.

### Regression & Guard Rules

1. **Validation Readiness Gating:** `ai-orch tasks use-cases validate <UC###>` refuses execution (exit 2) unless the use case is `ready`, `verified`, or `failing`. Use `--force` to bypass for exploratory probing (recorded as forced in the validation log).
2. **Campaign Scope:** `ai-orch tasks use-cases campaign` only executes probes for ready use cases (`ready`, `verified`, `failing`). Non-ready use cases (`draft`, `planned`, `in development`) are listed in the report under "Not ready (N/M)" with their current progress and left untouched. `untested` probes (missing scripts, timeouts) are excluded from the readiness score denominator.
3. **Regression Queue:** When a task linked to a `verified` use case is redelivered, bounced, or reopened, the engine marks `revalidation: pending` on the use case and enqueues it in `ai-orch tasks use-cases queue`.
4. **Safe Closing Guard:** A task cannot transition to `verified` or `done` if any linked approved use case is `failing`, unless that use case passed validation *after* the task was last delivered. The `--owner-approved` flag overrides this guard and is recorded in the task history and audit events.

## CLI fallback (`ai-orch tasks …`)

When a session has no broker MCP tools, use the version-free launcher (`~/.local/bin/ai-orch`, or `ai-orch` on `PATH`; see "Reaching the task engine" above):

```bash
# Search, create, approve, link, or validate use cases
ai-orch tasks use-cases list [--stage <stage>] [--approval proposed|approved|deprecated] [--tasks-dir tasks] [--json]
ai-orch tasks use-cases search <text> [--actor A] [--tasks-dir tasks] [--json]
ai-orch tasks use-cases create --title T [--actor A] [--approval proposed|approved|deprecated] [--json]
ai-orch tasks use-cases approve|deprecate|propose [UC###[,UC###...]] [--stage <stage>] [--approval <current>] [--all] [--reason TEXT] [--by NAME] [--apply --expect-plan-hash <hash>] [--json]
ai-orch tasks use-cases validate <UC###> [--force] [--timeout 60] [--json]
ai-orch tasks use-cases campaign [--filter-actor A] [--timeout 60] [--json]
ai-orch tasks use-cases queue [--tasks-dir tasks] [--json]
ai-orch tasks use-cases adopt-links [--expand-initiatives] [--apply --expect-plan-hash <hash>] [--json]
ai-orch tasks use-cases migrate-lifecycle [--apply --expect-plan-hash <hash>] [--json]
ai-orch tasks link <task_id> <UC###[,UC###]> [--apply --expect-plan-hash <hash>] [--json]
ai-orch tasks unlink <task_id> <UC###[,UC###]> [--apply --expect-plan-hash <hash>] [--json]

# List, show, or validate tasks
ai-orch tasks list [--tasks-dir tasks] [--json]
ai-orch tasks config [--tasks-dir tasks] [--json]
ai-orch tasks validate [--tasks-dir tasks] [--json]
ai-orch tasks sync-index [--tasks-dir tasks] [--apply | --check] [--json]
ai-orch tasks merge-index [<base> <ours> <theirs>] [--tasks-dir tasks] [--json]

# Create, transition, or update tasks
ai-orch tasks new --category C --title T --short S --priority P --priority-reason R --goal G [--use-case UC001] [--from-use-case UC001 [--steps 1-3]] [--kind feature|fix|chore|docs|investigation] [--json]
ai-orch tasks transition <task_id> <new_state> [--actor <actor>] [--verifier <verifier>] [--verify-by <target>] [--verify-check <check>] [--reason "<text>"] [--json]
ai-orch tasks set-verify-by <id> <target> [--check <what-to-check>] [--json]
ai-orch tasks request-verification <id> --by <target> [--check <what-to-check>] [--json]
ai-orch tasks verification-queue [--for <workspace-slug>] [--all-workspaces] [--json]
ai-orch tasks set <task_id> <field> <value...> [--expect-hash <hash>] [--json]

# Manage blocking questions and inbox notes
ai-orch questions list [--status open|answered|withdrawn|moved|unapplied|all] [--json]
ai-orch questions ask --question "..." --short "..." --context "..." --option "A=..." [--blocks T###|-] [--notes "..."] [--json]
ai-orch questions answer Q### --choice A [--text "..."] [--apply-ref <ref>] [--note "..."] [--json]
ai-orch questions apply Q### --note "..." [--ref "..."] [--json]
ai-orch questions move Q### --to <tracker-url-or-ref> [--reason "..."] [--json]
ai-orch inbox add --title "..." --kind idea --body "..." [--json]

# Ship, archive, reopen, or upgrade a tasks/ tree
ai-orch tasks ship <id> [--dry-run] [--expect-plan-hash <hash>] [--json]
ai-orch tasks archive [--dry-run] [--expect-plan-hash <hash>] [--json]
ai-orch tasks reopen <id> --reason "..." [--dry-run] [--expect-plan-hash <hash>] [--json]
ai-orch tasks upgrade [--tasks-dir tasks] [--migrate-plans] [--apply --expect-plan-hash <hash>] [--dry-run] [--preview] [--json]
```

## Upgrading an Existing Project to the Latest Convention

When working on a project created with older conventions (e.g. legacy `macroplan-authoring v0.1` without emergent tasks, or missing `tasks/AGENTS.md` rules, or lacking `Next up` / `Tasks by category` in `00-INDEX.md`):

1. **Via CLI (`ai-orch tasks upgrade`)**:
   ```bash
   ./bin/ai-orch tasks upgrade [--tasks-dir /path/to/project/tasks]
   ./bin/ai-orch tasks upgrade --apply --expect-plan-hash <plan_hash> [--tasks-dir /path/to/project/tasks]
   ```
   This non-destructively:
   - Appends or refreshes a managed block (`<!-- ai-orch:managed begin -->` … `<!-- ai-orch:managed end -->`) in `tasks/AGENTS.md` with the canonical `task-pipeline` rules and skill names, preserving all project-specific content outside the markers byte-for-byte;
   - Scaffolds standard directories (`_inbox/to-analyze`, `_inbox/analyzed`), `tasks/.gitignore`, and `tasks/.gitattributes` (`00-INDEX.md merge=ai-orch-index`), and registers `merge.ai-orch-index.driver` and `merge.ai-orch-index.name` in the repository's local git config;
   - Re-syncs `tasks/00-INDEX.md` while preserving project-specific extra table columns (e.g. `Owner`), `Next up` ordering (unless `--reorder` is passed to `sync-index`), and each table's `Id` cell format (putting `short` into the `Task` link text when the `Id` column uses bare `T###` IDs);
   - Runs `validate` across the tree and exits `0` on success.

2. **Via Skill (in Chat)**:
   Ask the assistant in your project window:
   > *"Use the `task-pipeline` skill to upgrade this project's `tasks/` directory to the latest model, align `tasks/AGENTS.md`, and run `ai-orch tasks sync-index --apply`."*
   The assistant inspects the tasks, updates the rules, assigns `profile: bulk-execution` or `deep-reasoning` to active tasks, and validates the result.

## Normalizing existing tasks (any project, any age)

`tasks upgrade` fixes the scaffolding (rules, folders, index tables); it does **not** rewrite plans or task files. Projects written by hand or by older sessions drift in ways only a reader can fix: task lists as bullets or tables, ids that collide with emergent ids (`T1` inside a plan), states that contradict the log, work done as emergent tasks but still "in progress" in the plan, closed initiatives left among open ones. When asked to normalize (or when `tasks list` shows synthetic `INIT-NN` cards, i.e. a plan whose tasks the engine cannot see), do this:

1. **Inventory, read-only.** Run `ai-orch tasks validate --json` and `ai-orch tasks list --json`. For every `NN-<slug>/plan.md`, record: does the engine see its tasks (`kind: initiative_task` rows with `NN.T` ids)? which ids does it use? A plan with no rows, or rows with ids not shaped `NN.T`, needs work. Read `00-INDEX.md`, the plan's log, and the emergent tasks that reference the initiative (e.g. titles ending `(08-T3)`).
2. **Decide the target per plan, then write it.** Each task becomes a canonical block, keeping the original wording of goal, steps and verification:

   ```markdown
   ### NN.T - <title>

   - **Status:** `<state>` (<date if known>) · **Profile:** `<profile>` · **Depends on:** <NN.T ids or -> · **Repo:** `<repo or ->`
   - **Goal:** ...
   - **Verification:** ...
   ```

   - **Ids:** `NN.1, NN.2, ...` in the plan's order; a sub-letter task (`T2b`) becomes its own number. Never reuse `T###` for plan tasks (that namespace belongs to emergent tasks). Rewrite the plan's internal references (`T3` → `NN.3`, "depends on T1") in the same edit.
   - **State:** from evidence only (the log, merged commits, the emergent task that executed it, `done/`), never from optimism. When a plan task was executed as an emergent task, set the plan task to that task's state and add `executed as [T###](path)`; do not duplicate the work.
   - **Unknowns** (a state you cannot establish, a dependency that is ambiguous) become blocking questions (`questions ask`), not guesses.
   - Text outside the task section (goal, design, log, open questions) stays as it is; append a log line: `<date> — tasks normalized to the NN.T convention (ids T1..T7 → NN.1..NN.8)`.
3. **Initiative state and placement.** When every task is closed, the initiative is done: write `summary.md` and move the folder under `done/` (fixing links that pointed into it), as for any completed initiative. Mark an initiative `in progress` only if a task is.
4. **Index and check.** `ai-orch tasks sync-index --check`, review the diff, `--apply`; then `validate` must show no errors and `tasks list` must show every plan task with an `NN.T` id and no `INIT-NN` card for a plan that has tasks.
5. **One commit per project** (`docs(tasks): normalize plans to the NN.T convention`), touching only `tasks/`. If another session is working in the same repository, do it in a worktree and fast-forward, so concurrent task edits surface as conflicts instead of being overwritten.

## Tooling feedback

When you hit friction, a defect, a missing feature or a wrong default in `ai-orch`, its UI, the VS Code extension or the delegation tooling, or when a new need appears, report it at once with `ai-orch feedback`:

```bash
ai-orch feedback --kind bug|feature|idea|request --title "<short>" --body "<what, where, expected vs actual>"
```

- **Report immediately:** do not work around tooling issues silently.
- **One note per item:** capture what you ran, what you expected, and what happened.
- **No sensitive data:** never include secrets, private hostnames, or audit findings in notes.
- **Triage:** maintainers triage notes into tasks and reply with the task ID and short title.

## Reference

See [`references/template.md`](references/template.md) for copy-paste skeletons
of every file kind (`CONTEXT.md`, `00-INDEX.md`, `specs/<slug>.md`, `plan.md`
inline and expanded, `NN.T-<name>.md`, `summary.md`). A real, in-use `tasks/`
tree looks like: specs driving initiatives, completed initiatives under
`done/`, and an `_inbox/` with analyzed provenance.
