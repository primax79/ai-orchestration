# Spec: Blocking questions (format, engine, pending-answers UI)

- **Status:** draft for review (2026-10-16)
- **Drives:** initiative [08](../08-blocking-questions/plan.md)
- **Extends:** [`task-and-state-model`](task-and-state-model.md). The `decider` header and the `## Decisions waiting` table become views over question files.
- **Depends on:** [`control-plane-safety`](control-plane-safety.md) (generated index regions, UI auth, confirmation modal). The "answer and resume" action depends on [`agent-runs-from-ui`](agent-runs-from-ui.md).

## 0. Amendments after review 2 (normative; each overrides the section it names)

- **Q1 — §2 `blocks` accepts leaf node IDs at any depth** (spec subtasks S4, §3; overrides review 2 restriction): emergent tasks (`T###`), initiative tasks (`NN.T`), and child tasks (`07.4.2`, `T014.1`). Containers cannot be blocked; a question about a container blocks the leaves the asker names (S4).
- **Q2 — §2 the prior state is recorded in the question.** The header field `blocks` records each blocked task's state at the time of asking: `blocks: T013 (in progress), T014 (open)`. The restore uses this value. `PROGRESS.md` is not used for this, because single-file tasks have none.
- **Q3 — §3 several questions on one task.**
  - `ask` also links a task that is already `waiting` because of other questions: it appends to `decider` (`Q004, Q007`) and records `(waiting)` as the prior state in the new question.
  - A task is restored only when **all** questions in its `decider` are answered or withdrawn. It goes back to the prior state recorded by the **earliest** linked question (the state before the first question).
  - Asking against a task that is `waiting`/`blocked` for a non-question reason, or in a terminal state, is refused.
- **Q4 — §3 one lock for the whole operation.** `ask`, `answer` and `withdraw` hold the `tasks/.ai-orch.lock` (spec 06 A9) across id allocation, validation, the exclusive file creation (`O_EXCL`) and every task update. If any step fails, the files already written are rolled back. A concurrent test covers two asks on the same task.
- **Q5 — §3 the waiting invariant.**
  - `tasks transition` refuses to move a task out of `waiting` while its `decider` lists an open question; only `questions answer` / `withdraw` may do that.
  - `--force-unblock --reason` exists for the owner, and it withdraws the open questions with that reason.
- **Q6 — §2 withdrawn questions.** `## Answer` uses `choice: withdrawn` with `answered-by` and `answered` filled in, and the reason as text.
- **Q7 — §2 answer text is multi-line-safe (overrides the `text` bullet).**
  - `## Answer` has three bullets: `choice`, `answered-by`, `answered`.
  - The free text follows as a fenced block (` ```text `). Its fence is longer than any backtick run in the text.
  - An empty text means no block.
  - The same rule applies to option consequences and to the context: they are Markdown and never parsed as headers.
  - Tests cover newlines, colons, pipes, headings, Markdown and Unicode.
- **Q8 — §4 questions from agent runs go through the supervisor only.** An agent in a run never calls `questions ask` (its worktree has a different `tasks/` and its sandbox may forbid writing to the main workspace).
  - The agent emits the ` ```ai-orch-question ` block as the last thing in its final message.
  - The **run supervisor** files the question in the **main workspace**.
  - The supervisor injects `asked-by` (`<tool>:<profile>`) and `origin-run` itself, and forces `blocks` to the run's own task. It ignores any `blocks` value in the block.

  Interactive sessions (not runs) use `questions ask` directly.
- **Q9 — §3 `--from-task` output.** It produces a valid **pure open question**:
  - `question` is the legacy text, made to end with `?`;
  - `## Context` holds `Converted from the legacy decider header of T###; context to be completed by the owner.`;
  - the options are empty, with `open-answer: yes` and `recommended: -`;
  - the validator warning is `context-not-completed`.
- **Q10 — §5 rendering.** The context and options are rendered under spec 06 A12 (HTML escaped, safe links, CSP).
- **Q11 — §2 origin-session header field** (spec 12 E10). Added directly after `origin-run`: records the session ID or role that asked the question (e.g. `orchestrator`), enabling `resume-origin` or routing answers back to the originating session. Defaults to `-` when absent. When both `origin-run` and an origin role exist, the run takes precedence for `resume-origin`.

## 1. Problem

Today a blocking question is a free-text `decider: owner: <question>` header on a task, plus a hand-written row in `## Decisions waiting`. That is fine for a person reading the file, but:

- it has no stable key;
- it does not separate the question from its context;
- it lists no answer options and has no machine-readable answer;
- it has no lifecycle.

An agent cannot ask in a way the UI can render as a form, and an answer cannot flow back to the session that asked.

## 2. Format

One question = one file, `tasks/questions/Q###-<slug>.md`.

- `Q###` is the **key**: unique across the whole `tasks/` tree, never reused, reserved by creating the file (the same rule as `T###`).
- `questions/` becomes a reserved directory (`RESERVED_DIRS`).
- Answered and withdrawn questions stay where they are, so the history is the directory.

```markdown
# Q004 Default permission mode for headless Claude runs

- id: Q004
- question: Which permission mode should headless Claude runs use by default?
- status: open
- blocks: T013, 07.3
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-16
- origin-run: -
- origin-session: -
- open-answer: yes
- recommended: A

## Context

Headless runs cannot show permission prompts. `acceptEdits` lets the agent edit files but denies any tool that would prompt
(Bash outside the allow-list, MCP tools), so an orchestrate run may stall. `bypassPermissions` never stalls but lets the agent
run anything on this machine. A middle ground is an explicit `allowed_tools` list per tool in `orchestration.toml`.

## Options

- **A** — `acceptEdits` plus an explicit allow-list: safe default; stalls are visible in the run log.
- **B** — `bypassPermissions`: never stalls; full machine access for every run.
- **C** — Per-run choice in the Run dialog, default A.

## Answer

- choice: -
- text: -
- answered-by: -
- answered: -
```

**Header** (a closed set, in this exact order; same `- key: value` grammar as task headers):

| Field | Required | Values |
| --- | --- | --- |
| `id` | yes | `Q###`, equal to the filename prefix |
| `question` | yes | **Short text**, one sentence, at most 160 characters, ending with `?`. It must stand alone: no "this", "the above", or references to the context section. |
| `status` | yes | `open`, `answered`, `withdrawn` |
| `blocks` | yes | comma-separated leaf task ids (`T###`, `NN.T`, `07.4.2`, `T014.1`), or `-` |
| `decider` | yes | `owner`, or a named role or person |
| `asked-by` | yes | `<tool>:<profile>`, `owner`, or a session name |
| `asked` | yes | ISO date |
| `origin-run` | yes | run id (spec 07) when asked from an agent run, else `-` |
| `origin-session` | yes | session id or role (`orchestrator`) when asked from a registered session, else `-` |
| `open-answer` | yes | `yes` or `no`: whether free text is accepted instead of, or in addition to, an option |
| `recommended` | yes | an option label, or `-` |

**Sections** (all required, in this order):

- `## Context` — the explanation: what is at stake, the facts the decider needs, and the consequences of each choice. Free Markdown.
- `## Options` — one bullet per option: `- **<LABEL>** — <short label>: <consequence>`.
  - Labels are `A`, `B`, `C`… unique within the question, and at least 2 options are required.
  - The recommendation lives only in the `recommended` header; the bullets carry no "(recommended)" marker, so the two can never disagree.
  - When `open-answer: yes`, the options may be empty (a pure open question), but then `recommended` must be `-`.
- `## Answer` — exactly four bullets, filled only by `questions answer`:
  - `choice` (a label, or `open`);
  - `text` (free text, or `-`);
  - `answered-by`;
  - `answered` (ISO date).

  `choice: open` requires `open-answer: yes` and a non-empty `text`.

**Task linkage:**

- A task blocked by questions is in state `waiting`.
- Its `decider` header becomes `Q004` (or `Q004, Q007`).
- The legacy free-text form `owner: <question>` stays valid. `tasks validate` warns on it and suggests `questions ask --from-task`.

## 3. Engine (`ai-orch questions`)

In `tasks_engine.py` (same parser, same validator, stdlib only). Every subcommand supports `--json`.

| Command | Effect |
| --- | --- |
| `questions list [--status open\|answered\|withdrawn\|all] [--blocks ID]` | Parsed questions, open first, then newest first. |
| `questions show Q###` | One question with its context, options and answer. |
| `questions ask --question TEXT --context TEXT\|--context-file PATH --option "A=<label>: <consequence>"... [--recommended A] [--open-answer yes\|no] --blocks IDS [--decider owner] [--asked-by X] [--origin-run RUN]` | Allocates the next free `Q###` (with a file lock), writes the file, validates it, and moves every `blocks` task currently `open`/`in progress` to `waiting` with `decider: Q###`. Returns the id. |
| `questions ask --from-task T###` | Converts a legacy `decider: owner: <text>` into a question file (context and options left empty for the owner to fill: `status: open`, validator warning). |
| `questions answer Q### --choice A\|open [--text TEXT] [--by owner]` | Validates the answer against the options and `open-answer`, fills `## Answer`, sets `status: answered`. For each blocked task whose open questions are now all answered, it sets the state back to the one before `waiting` (taken from the task's `PROGRESS.md` log, else `open`) and restores `decider: -`. |
| `questions withdraw Q### --reason TEXT` | `status: withdrawn`, reason appended to `## Answer` as `text`, tasks unblocked as above. |

- `tasks validate` checks every question file: the header set and order, the sections, the option labels, the `recommended` label, the question length and `?`, the answer consistency, `blocks` ids that exist, and status consistency with the blocked tasks.
- `sync-index` renders `## Decisions waiting` (a generated region, see spec 06) from the **open questions**:

  | Key | Question | Blocks | Decider | Recommended |
  | --- | --- | --- | --- | --- |
  | [Q004](questions/Q004-headless-permission-mode.md) | Which permission mode should headless Claude runs use by default? | T013, 07.3 | owner | A |

## 4. Agents asking

- The task-pipeline and orchestration skills (the protocol-agnostic templates in `plugins/`) state the rule: an agent that hits a decision it must not take files it with `questions ask` (or, when it has no shell, emits the block below as the **last** thing in its final message) and stops. It never asks in prose only.
- The question must stand alone, and the context must contain everything the decider needs: the decider may read only the question card.
- Machine-emitted fallback block, parsed by the run supervisor (spec 07) and filed through `questions ask`:

  ````markdown
  ```ai-orch-question
  {"question": "...?", "context": "...", "options": [{"label": "A", "title": "...", "consequence": "..."}], "recommended": "A", "open_answer": true, "blocks": ["T013"]}
  ```
  ````

## 5. Pending-answers UI

- **Navbar badge** with the count of open questions, linking to a **Decisions** tab.
- **Decisions tab:**
  - open questions grouped by the task they block, oldest first;
  - each card shows the key, the short text, the blocked tasks, `asked-by` and age;
  - the context is collapsible and rendered as Markdown;
  - options are radio buttons, with the recommended one badged;
  - a text area appears when `open-answer: yes` and is required for `choice: open`;
  - Submit → confirmation modal (spec 06) → `questions answer`;
  - Withdraw needs a reason.
- **When `origin-run` is set** and that run has a `session_id`, the card also offers **"Answer and resume run"**. It answers, then starts a `--continue` run (spec 07) whose instructions are the formatted answer:

  ```text
  Answer to Q004 (Which permission mode...?): A — acceptEdits plus an explicit allow-list. <text>
  ```

- **Answered/withdrawn history**, filterable, read-only.
- **Task modal:** a "Questions" section lists the task's questions with status, and "Ask a question…" opens the same form an agent would fill (question, context, options, recommended, open answer).
- **VS Code:** the existing "Decisions Waiting" tree lists open questions (key and short text). A click opens the webview Decisions tab on that card.
