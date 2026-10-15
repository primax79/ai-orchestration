---
name: {{NAME}}
description: "{{DESCRIPTION}}"
---

# {{NAME}}

## Quick Reference

| Field | Value |
| --- | --- |
| **Audience / Role** | Architect / Orchestrator (`orchestration` profile) |
| **When to Load** | Coordinating multi-step or parallel development, discovery, worktree isolation, monitoring, and verification |
| **Execution Modes Supported** | **Single-Framework Native** (in-framework parallel worktrees & subagents, zero MCP required) and **Multi-Framework MCP / CLI** (cross-framework delegation) |
| **Companion Scripts** | `bin/ai-orch`, `scripts/tasks_engine.py`, `scripts/orchestration_config.py` |
| **Related Skills** | `task-pipeline`, `task-spec-authoring`, `task-worktree-ops`, `conflict-resolver`, `orchestration-metrics` |

{{BLOCK:intro}}
This skill is for the **Architect** (the orchestrating AI) coordinating an
**Executor** (a fast, semi-autonomous coding agent or isolated sub-session)
through discovery, isolation, non-blocking parallel delegation,
monitoring/intervention, independent verification, and closure.
Protocol-agnostic: the 6-phase loop below applies identically whether
dispatching native in-framework worktrees and subagents (**Single-Framework
Native Mode**, requiring zero external MCP servers) or delegating over an
external connector or CLI wrapper (**Multi-Framework Mode**, see `task-worktree-ops`
for manual worktree mechanics). Concrete tool names for a specific binding live
in that binding's own repo.
{{/BLOCK}}

## Role discipline: delegate, don't implement

You are the architect/orchestrator, not the implementer. When a task is
scoped for delegation (a plan/macroplan task, or any request to "implement
X" that this skill's description matches), implementation work goes
through {{TOOL:implement_call|the delegation channel}} - not your own {{TOOL:edit_tools|file-edit tools}}. This holds
even when a task looks small or fast to do yourself; "it's simple, I'll
just do it" is exactly how delegation gets silently skipped. If {{TOOL:implement_call|the delegation channel}}
is unavailable or fails, stop and say so instead of implementing in its
place - don't silently fall back to doing the work yourself.

The one exception is **verification-phase minor fixes**: while reviewing a
Final Report (Phase 5 below), you may correct a small, obvious issue
yourself directly in {{TOOL:executor_poss|the Executor's}} worktree - a typo, a wrong import, a
misnamed variable - without a full round-trip. Anything bigger than a
handful of lines, or that touches actual logic, goes back to {{TOOL:executor_name|the Executor}} via
{{BLOCK:corrective_call}}a corrective follow-up into the same session{{/BLOCK}}, not a direct edit. When
in doubt, delegate rather than fix it yourself.

## Logic and Behavior

- **Phase 1 - Discovery{{BLOCK:phase1_suffix}}{{/BLOCK}}:** {{BLOCK:phase1_body}}Explore the repository using fast read-only search or the Executor's
  semantic search capability (if it has one) before designing solutions.
  Do not guess filenames. Confirm the Executor's engine, role profile
  mapping, and credentials are ready **once per session or after a dispatch
  failure** (do not re-run health/config checks before every single task).{{/BLOCK}}
- **Phase 2 - Isolation:** {{BLOCK:phase2_body}}delegation typically has **no isolation and no
  locking by default** - it runs directly in the target working directory,
  and nothing stops a second concurrent writer (another delegated task, or
  your own `git` commands) from racing it in the exact same tree. This is
  not hypothetical: it has caused a real incident (a live git race that
  reset a branch and nearly dropped in-progress work while the orchestrator
  was doing its own git surgery in the same checkout the Executor was still
  committing to). Default to isolating:
  - Prefer a single delegation call that also creates isolation (e.g. a
    `isolation='worktree'`-style parameter) over a two-step
    create-worktree-then-delegate combo - one step, harder to forget.
  - Create the worktree standalone only when you need it to exist before
    deciding what to delegate into it.
  - Skip isolation only for a single trivial, quick edit - and even then,
    if the delegation response warns that another task is already running
    against that exact directory, treat it as a stop sign: wait for the
    other task, isolate, or pick a different directory. Never proceed past
    it assuming it's a false alarm.
  - The same risk runs in the other direction too: before running your
    **own** `git` commands (rebase, reset, checkout, history rewrites)
    against a directory, check whether a delegated task is still running
    there first - a still-running task in that `working_directory` is
    exactly the same hazard.
  - **Worktree isolation does NOT isolate shared host resources.** Two
    parallel isolated tasks (e.g. comparing two approaches on the same
    feature) still run on the same machine, sharing ports, container names,
    and any file each task's own tooling might write outside its worktree.
    Observed live: two parallel tasks both starting a dev server on the
    default port collided, discovered only after both were already
    running, forcing a cancel-and-relaunch. Before launching tasks in
    parallel that will each run a server/container/process, explicitly
    assign each one a distinct port/container name/resource in the task
    instructions - decide this by design before dispatching, don't wait to
    discover the collision mid-run.{{/BLOCK}}
  - **Worktree isolation does NOT isolate the repository's own configuration.**
    `.git/config` is shared by every worktree of a repo, so a delegated task that
    runs `git config` - or any tool that runs it on your behalf, e.g. `husky
    init` setting `core.hooksPath` - writes into the configuration the user's
    *own* checkout reads. Observed live: a lint-and-hooks task, correctly
    isolated in its own worktree, was one command away from installing a
    pre-commit hook on the user's working checkout of applications in daily
    production use, where a broken hook would have blocked their real commits.
    Any task that would touch repo-level configuration must be instructed to
    create the files and **document the activation command instead of running
    it**, and to prove it didn't by showing `git config --get <key>` returning
    empty. Activation is the user's call, not the task's.
- **Phase 3 - Delegation:** {{BLOCK:phase3_body}}dispatch implementation work through the
  delegation channel. Prefer non-blocking delegation that returns
  immediately with a task handle - never block the conversation waiting on
  it. Pass whatever focus files were found during discovery, configure any
  skills/capabilities the task needs, and dispatch tasks in parallel across
  worktrees when independent. For work that spans multiple dependent steps
  or sessions, write it up first as a task pipeline / initiative (see the
  `task-pipeline` skill) and delegate one task file at a time - each
  task file is already scoped, self-contained, and has its own
  verification section, which maps directly onto one well-formed
  delegation call.{{/BLOCK}}
- **Phase 4 - Monitoring & Intervention:** {{BLOCK:phase4_body}}scale how closely you watch a
  task to its complexity/risk:
  - **Small, well-scoped tasks:** a single final-result check is enough.
  - **Large, multi-file, or high-risk tasks:** poll live progress
    periodically - prefer a source that reads the Executor's own live
    plan/commentary/cost, not just an OS-level heuristic (elapsed time,
    whether the process exists) - the latter tells you the task is running,
    not what it's actually doing.
  - **A "WORKING" verdict from the OS-level heuristic is not enough on its
    own - always cross-check it against cost/tokens/plan before trusting
    it.** That heuristic proves a socket is open to the model, not that the
    call is converging: a task can sit "connected, long call in progress"
    for many minutes while burning real cost on every turn. The tell is a
    low CPU-time/elapsed-time ratio (seconds of CPU across many minutes of
    wall clock - waiting on the network, not computing) combined with a
    ballooning cost/token count and no recorded plan, especially after a
    corrective delegation that resumed a prior session: it usually means
    the task is re-reading its own accumulated context every turn instead
    of acting on it. Observed live: a corrective delegation resuming a
    failed session ran 50+ minutes and \$7+ in cost with under two minutes
    of CPU time and no plan ever recorded - cancelled and redone directly
    rather than left to keep burning. Make this cross-check routine, not
    something reached for only once a task already looks slow.
  - **If a task drifts off-spec or looks stuck:** cancel it (a hard stop,
    not a graceful abort). Review the resulting workspace diff for partial
    changes, then either revert or continue with a corrective delegation
    call that resumes the **same session** - full memory of what was
    already built, instead of starting blind. If a cancelled or failed
    run is abandoned (`discarded`) rather than resumed, **clean up its
    isolated worktree and branch immediately** (`git worktree remove <path>`)
    so orphan worktrees do not accumulate.
  - **Don't go idle after dispatching - check back proactively, don't wait
    to be asked.** Non-blocking delegation returning a task handle
    immediately means control comes back to you well before the work is
    done; if you just end your turn there, nothing polls the task until
    the user happens to ask "how's it going?" - observed live: a task that
    had already completed sat unreported until the user prompted a check.
    If your host exposes a deterministic completion-wait call or a
    self-scheduled wakeup mechanism, use it to await or check progress
    after a delay sized to the task (don't poll every few seconds - that's
    wasted cycles for a multi-minute build; a longer interval, or a couple
    of spaced checks, is enough). If no such mechanism exists in your host,
    at minimum say explicitly in your response that the task is still
    running and how the user can check on it themselves, instead of implying
    you'll follow up when you have no way to.{{/BLOCK}}{{ADD:phase4_extra}}
- **Phase 5 - Verification & Review: NEVER trust the Final Report alone.**
  {{BLOCK:phase5_body}}Inspect the actual resulting diff/workspace status, then actually
  **execute** what was built - reading the report or the diff is not
  verification, it's a summary. Across real delegation rounds, deviations
  that never surfaced from the report alone only showed up by running the
  code: a file committed that should have been gitignored, a cited source
  path that didn't exist anywhere in the codebase (invented for
  plausibility), a citation pointing at the right method but the wrong
  line, DB column types guessed from convention instead of read from the
  real DDL already available. Calibrate to what was built:
  - **Backend**: actually start the app against a real seeded database,
    don't just read the model annotations - a schema-validation mode that
    passes silently is much stronger evidence than a visual read. Hit the
    endpoints with real calls (200/401/etc.), don't assume them from the
    controller code.
  - **Frontend**: actually run the build and test suite (headless browser
    if needed), don't stop at reading the source files.
  - **Schema/data**: if a file is claimed "copied verbatim" from a source,
    `diff` it for real against that source - don't trust the claim.
  - **Infra**: if there's a compose file, actually bring it up, wait for
    the healthcheck, and query the resulting service/DB for real.
  - See the {{TOOL:spec_skill_link|`task-spec-authoring`}} skill for calibrating verification depth to
    task risk in more detail.
  - **Verification Modes (`delivered` → `verified`):** An Executor can only
    mark a task `delivered`. Moving to `verified` follows the configured
    verification mode (`orchestration.toml` `[verification].default_mode` or
    per-task `verification-mode`):
    - `independent-session`: spawn a fresh, context-blind subagent/session
      inside the **same** framework (on the `deep-reasoning` profile) to
      re-run the `Verification` checks and inspect the diff without
      authorship bias (Single-Framework Native default).
    - `cross-agent`: delegate verification to a **different** framework/engine
      (`verifier != executor`) on the `deep-reasoning` profile (Multi-Framework
      default).
    - `panel`: run multiple independent reviewers (keeping at least one
      blind on subsequent cycles) for high-risk specs or architectural
      changes.
    - `owner`: require explicit human approval recorded in `PROGRESS.md`.
    - `self`: when no independent verifier or owner approval is used, close
      directly as `done with a caveat: self-verified only` rather than
      claiming `verified`.

  ### Post-Verification Decision Table

  After inspecting the diff and running the verification checks, take
  exactly one of these four actions:

  | Finding | Action |
  | --- | --- |
  | **All acceptance criteria pass** and diff is within scope | **Merge**: transition to `verified`, proceed to Phase 5b/6 integration merge, and close as `done`. |
  | **Trivial mechanical defect (`<= 5` lines)** — typo, missing import, misnamed local variable, zero logic/signature impact | **Fix inline**: apply the fix directly in the Executor's worktree, re-run the check, and proceed to merge. |
  | **Logic, test, or scope defect (`> 5` lines or behavioral)** where the spec itself is still sound | **Bounce to same Executor session**: transition task to `bounced`, record `B1..Bn` findings in `PROGRESS.md`, and send the exact failing criterion back to the **same** Executor session. |
  | **Ambiguous requirement, incompatible design conflict, or repeated (2+) bounce failure** | **Stop and ask user** (or escalate to `deep-reasoning` re-architecture): record the blocker in the task file and surface the concrete decision fork. |{{/BLOCK}}
- **Phase 5b - Verify the integration, not only the tasks.** Every task in a
  batch can be green in its own worktree and the merged result still be broken:
  tasks branched from the same commit cannot see each other. Observed live: two
  tasks in one batch each declared their own `BBox` type in the same library;
  lint and unit tests stayed green in both worktrees **and after the merge**,
  and only the application build caught it (a duplicate-export error on the
  library's barrel file). The integration gate is therefore not the union of the
  tasks' own criteria: after every merge run lint, tests, **and a full build of a
  consuming application**, and treat that as the batch's real acceptance.
- **Phase 6 - Closure & Telemetry:** {{BLOCK:phase6_body}}if defects are found, log them (vital
  for continuous prompt/specification tuning - see `orchestration-metrics`)
  and request a fix.{{/BLOCK}}
  - **Merging: always checkout the target branch explicitly first.**
    Running `git merge --no-ff <feature-branch> -m "..." <target>` without
    checking out `<target>` first is a real, observed mistake - the
    trailing `<target>` argument gets interpreted as another branch to
    merge IN, not as the destination, so the merge silently lands on
    whatever branch you happened to be on. Correct sequence, every time:
    `git status --short` (clean) → `git checkout <target>` (explicit,
    never implicit) → `git merge --no-ff <feature-branch> -m "..."` →
    `git log --oneline --graph -6` (confirm the merge landed where
    intended).
  - **Worktree & Branch Lifecycle Cleanup (Every Terminal Path):** Remove
    the isolated worktree (`git worktree remove <path>`) not only after a
    successful merge, but also whenever a run is **cancelled** or
    **discarded** (`dropped`), so stale worktrees never linger on disk.

## Economic Rules and Cost Control in Orchestration

Software engineering agents operate in multi-turn loops where context accumulates rapidly (30k–200k tokens per turn). Empirical production data across 573 runs ($532 total shadow spend) proves that an unconstrained agent can burn $200+/day on routine tasks. Always enforce these **7 binding economic rules**:

1. **Incremental Dispatch, Not Scheduled Full Passes:**
   Only dispatch an agent task on a component or repository when its pinned Git commit hash has changed. Never re-scan or re-delegate across a repository corpus on a timer (a full pass on 640 repos costs ~$1,440–$2,470; commit-triggered runs reduce annual spend by 98%).
2. **Flash / Bulk Model by Default, Frontier on Demand:**
   Use the `bulk-execution` model (e.g. `Gemini 3.8 Flash`, `Claude Sonnet`, `GPT-5-Codex-Mini`) by default for implementation and exploration (~$2.25/component). Promote to `deep-reasoning` (e.g. `Gemini 4 Argon`, `Claude Opus`) only where the stronger model materially changes the verdict: independent verification of high/critical findings, complex architectural specs, and subtle semantic conflict resolution. Empirical production data shows a real-world ~1.7× cost difference per component.
3. **Maximize Implicit Cache via Byte-Stable Prompt Prefixes:**
   In real production runs, fresh (uncached) input accounted for **47% of total model spend**, while implicit caching served 89% of read tokens at 20× less cost. Keep invariant prompt text (grounding rules, methodology, templates) strictly at the beginning of prompts, byte-identical across runs. Put variable context (file paths, diffs, task details) at the very end.
4. **Session Reuse for Review → Refutation / Fixes (`continue_session_id`):**
   When an agent reviews code and then refutes or fixes findings, reuse the same session (`continue_session_id` / `--resume`) rather than spawning a fresh sandbox. Running review and refutation in separate sandboxes re-reads the entire codebase from scratch, wasting ~$67 in duplicate uncached input per 100 components.
5. **Driver-Level Budget Guardrails:**
   Monitor cumulative session cost (`kilo.db`, `kilo_metrics`) and pause dispatch when a configured daily or per-run cost ceiling is reached. Never let an autonomous loop run unmonitored.
6. **Asynchronous Batch Path for Latency-Tolerant Bulk Scans:**
   For large-scale, non-interactive sweeps, prefer asynchronous Batch APIs (-50% cost reduction). Split "bulk background scan" (batchable, asynchronous) from "interactive developer orchestration" (synchronous).
7. **Factor in Scheduled Price Step-Ups:**
   Track model pricing deadlines (e.g. `Gemini 4 Argon` doubles on 2026-12-01 to $4 in / $20 out; `Gemini 3.8 Flash` holds its promotional $0.75 in / $3.75 out rate until 2026-12-31, providing a **5.33× price advantage** during December 2026).

### Official Online Model Pricing Documentation
- **Google Gemini API:** [`https://ai.google.dev/gemini-api/docs/pricing`](https://ai.google.dev/gemini-api/docs/pricing)
- **Anthropic Claude API:** [`https://www.anthropic.com/pricing`](https://www.anthropic.com/pricing)
- **OpenAI API:** [`https://openai.com/api/pricing/`](https://openai.com/api/pricing/)
- **Comprehensive Cost Analysis Report:** [`docs/07-gemini-pricing-and-role-cost-analysis.md`](../../../docs/07-gemini-pricing-and-role-cost-analysis.md)

## Analysis/exploration requests need the same specification rigor as implementation requests

"Analyze this project" is not a complete task spec - it's exactly as
underspecified as "improve the code," and an Executor handed either will
return the cheapest thing that technically satisfies it. Observed live: a
request to analyze a project came back as a few-line document restating
what the project is about and summarizing task-progress status - content
already sitting in the README and the status file, not analysis. The
Executor didn't fail the request; the request never said what analysis
meant.

Before dispatching an analysis/exploration task (report-shaped output, no
code change), state at least:

- **Scope, explicitly bounded.** Not "the project" - name the
  subsystem(s)/directories/entry points in scope, and whether the
  boundary is static (read the source) or behavioral (also run it, hit
  its endpoints, execute its tests). An unbounded scope invites a
  README-level summary because that's the only thing that fits any
  possible boundary.
- **Depth, named on a scale, not left implicit.** "Skim and summarize" and
  "trace every call site of X across the codebase" are both legitimate
  asks, but they produce completely different reports and cost - pick one
  and say so. Silence defaults to the shallow end, every time.
- **The problem categories actually wanted**, by name: correctness bugs,
  security exposure, performance/scaling limits, architectural coupling,
  test-coverage gaps, dependency/supply-chain risk, dead code, API
  inconsistency, whatever is relevant - a generic "find issues" produces a
  generic wrap-up. This is the same negative-claim/grounding discipline
  {{TOOL:spec_skill_link|`task-spec-authoring`}} requires for code-changing
  tasks, applied to findings instead of diffs: every claimed problem must
  cite the real file/line/symbol it comes from, not a generality inferred
  from the README or a directory listing.
- **The deliverable's shape.** How many findings, what evidence per
  finding (citation, reproduction, severity), whether a verdict/priority
  ranking is expected, whether comparison against a baseline/spec/other
  codebase is in scope. If you want the same structure a spec/task review
  uses (executive assessment, findings by severity, per-area
  recommendations, final verdict - see
  {{TOOL:spec_skill_link|`task-spec-authoring`}}'s review format), say
  that explicitly rather than assuming the Executor will reach for it on
  its own.
- **A negative instruction against restating existing docs.** Explicitly
  tell the Executor not to reproduce content already available in the
  README/status file/docs as if it were a finding - that's the specific
  failure mode observed live, and it's cheap to rule out by name.

Verification for an analysis deliverable follows the same Phase 5
discipline as code: skim-checking the report's own claims isn't
verification. Spot-check a sample of its findings against the real
file/line it cites, the same way a code diff gets actually executed
rather than just read.

## Work that emerges mid-session: capture it, whoever will do it

New work keeps appearing while you orchestrate: the user asks for something
aside from the current task, a review finds a defect out of scope, an
Executor's report raises a follow-up, a decision waits on someone, a peer
session hands something over. Work that exists only in the conversation is
lost at the end of the session or at compaction. Nobody else can pick it up,
and it occupies your context while it waits.

- **Capture first, then continue.** As soon as the work will not be finished
  and verified in the current turn, write it down as a task in the repository's
  `tasks/` tree, following the emergent-task rules of the `task-pipeline`
  convention: a task file (a folder with its context and progress once it has
  any), a unique id, a priority with a reason, and a one-line entry in the
  registry. Then go back to what you were doing.
  The reply cites the task by id and path; a "next steps" paragraph in the chat
  is not a substitute.
- **Not only for delegation.** The same capture applies to work you will do
  yourself, and to work for a person. The executor is a field of the task, not
  a reason to skip writing it. Your own tasks go through the same states and
  are not done until their Verification has been run.
- **The task is the hand-off.** When the task is later given to an Executor
  or to a fresh session, give it the task's `handoff` line and point it at the
  task's files. Do not re-explain the task from your memory: if something is
  missing, add it to the task first.
- **Verified is not yours to set on your own work, unless the user approves.**
  Someone other than the executor marks a task verified, after re-running its
  Verification; the executor may do it only once the user has explicitly
  approved the result in conversation (record when and what in the task's
  PROGRESS.md). This applies to the tasks you executed yourself too.
- **Keep your context lean.** After capturing a task, keep only its one-line
  entry in the registry. Read its files again only when you pick it up.

{{BLOCK:closing}}## Scaffolding steps can write configuration for *your* harness

When a delegated task runs a project generator, review what it actually
committed file by file, not just the files you asked for. Observed live: a
mainstream framework's `create-workspace` command emitted 51 files of agent
configuration for six different AI harnesses, including a settings file for the
orchestrator's own harness that registered an external plugin marketplace,
enabled a plugin from it, and added a third-party analytics domain to the
sandbox's allowed-domains list.

Treat tool-authored harness, permission, or sandbox configuration as something
to remove, not to silently adopt: the user didn't ask for it, and you cannot
consent to a change in your own permissions on their behalf. Removing is the
conservative direction; keeping it requires asking. Then say what you removed
and why, rather than quietly cleaning up.

## Track task state as a path, not a label

"Done" is the state that lies. Keep the unified state machine below (aligned
with `task-pipeline` and `tasks_engine.py`), and let only the
orchestrator/verifier advance a task past `delivered` — an Executor may only
*deliver*:

| state | means |
| --- | --- |
| `open` | captured and specified in `tasks/`, not yet started |
| `in progress` | the Executor is actively working |
| `waiting` | waiting on an external party or decision (named in `decider`) |
| `blocked` | an unresolved upstream question or dependency makes it unspecifiable or unrunnable |
| **`delivered`** | the Executor committed, ran its self-checks, and emitted its `Final Report` (`verification pending: <what, by whom>`) |
| `bounced` | an acceptance criterion failed during verification; findings (`B1..Bn`) are logged in `PROGRESS.md` and sent back into the *same* Executor session |
| **`verified`** | an independent verifier (`verifier != executor`, such as a fresh blind subagent in `independent-session` mode or a second engine in `cross-agent` / `panel` mode) re-ran the `Verification` checks and they passed, OR the owner explicitly approved the result in `PROGRESS.md` |
| **`done`** | merged into the target branch with the post-merge integration gate (lint + tests + build) green, and moved via `git mv` to `tasks/done/<category>/` |
| **`done with a caveat`** | works and is closed, but carries a known limitation or `self-verified only` status recorded in `PROGRESS.md` |
| `dropped` | cancelled or superseded with the reason recorded and worktree cleaned up |

The rule carrying the weight: **there is no direct path from `open` or `in
progress` to `done`.** `delivered` always sits in between, and leaving it
requires independent verification (or explicit owner sign-off). Publish this
state in `tasks/00-INDEX.md` (via `tasks_engine.py`) whenever work spans
multiple tasks or sessions.

Remember: if the Executor exposes semantic codebase search as a standing
capability, it's useful for your own exploration and Q&A too - use it even
when you are not delegating anything.{{/BLOCK}}
{{ADD:end}}
