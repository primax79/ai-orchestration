# N072 Use cases drive tasks: dependency from use case to tasks, tasks born from use cases, validation gated on task state

- id: N072
- title: Use cases drive tasks: dependency from use case to tasks, tasks born from use cases, validation gated on task state
- kind: feature
- status: processed
- created: 2026-10-27T14:47:19.156937+00:00
- author: ai-coding-tools
- about: -
- produced: 17
- processed-by: ai-coding-tools-d8

Owner request 2026-10-27, after git-code-rag showed 39/41 use cases 'failing' (see N067): tasks should be tightly linked to use cases and originate from them; a use case must depend on its tasks.

Today: UC has a free 'linked-tasks' list; a task may carry 'use-cases:'; nothing enforces or uses the link; campaigns validate everything, including use cases whose tasks are not written or not delivered.

Proposal:
1. Single source of truth for the link: the task's 'use-cases:' field (emergent tasks) and a '**Use cases:**' segment in plan task status lines (initiative tasks). The UC's 'linked-tasks' becomes derived and kept in sync by the engine (like 00-INDEX rows), so the two can never disagree.
2. Tasks born from use cases: 'ai-orch tasks new --from-use-case UC###' (and 'tasks child'/'plan task' equivalents) pre-fills goal/verification from the UC scenario and acceptance criteria and links both ways. 'validate' warns on feature/fix tasks with no use case (kinds chore, docs, investigation exempt) and on non-draft use cases with no task.
3. Use case lifecycle derived from its tasks: draft (no tasks) -> planned (tasks exist, none started) -> in development (some open/in progress) -> ready (all linked tasks delivered/verified/done) -> verified | failing (only after a probe run). The UI shows this instead of a raw failing.
4. Gating: 'use-cases validate' and campaigns run only use cases in 'ready' or already verified/failing; others are reported as 'not ready (N/M tasks done)' and their status is not touched. Readiness score counts only in-scope use cases.
5. Regression trigger: when a task linked to a verified use case is delivered again (or reopened), the use case is queued for re-validation; a task cannot reach 'verified' while one of its use cases is failing (matches the rule already written in git-code-rag's plan: 'a task is verified only if the use cases it is linked to still hold').
6. Optional: 'depends-on' between use cases (UC needs UC), shown in the graph view.

Example data: git-code-rag/tasks/use-cases (41 UCs, UC031-UC040 post-v0 with no tasks) and its 01-prototype plan.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (d6520d1)
- Date: 2026-10-27 14:47:18 UTC

## Owner additions (2026-10-27)

- **The relation is many-to-many.** A task can serve several use cases and a use case needs several tasks. Both
  `use-cases:` on a task and the derived `linked-tasks` on a use case are lists; the engine keeps them consistent.
- **Use-case-first workflow for new work.** When a user asks for a new task or feature, the assistant (skill
  task-pipeline / orchestration-workflow) must:
  1. find the use cases related to the request (by text, actor, linked specs and tasks);
  2. propose updates to those use cases, or point out contradictions between the request and existing use cases
     (scenario, acceptance criteria, scope), and/or draft the missing use cases;
  3. get the use cases validated by the user (or the decider) before going further;
  4. only then write or update the specs and create the tasks, each linked to its use cases.
  Skipping straight to tasks is allowed only for chore/docs/investigation work, and the skill says so.
- Skill text to update: task-pipeline (Use Cases section, emergent-task capture), orchestration-workflow, and the
  `tasks new` / `use-cases create` commands (e.g. `tasks new` asks or accepts `--use-case UC###,UC###`).
