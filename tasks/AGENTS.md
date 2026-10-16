# tasks/ convention (task-pipeline + emergent tasks)

Short copy of the `task-pipeline` skill (`plugins/architect-side/skills/task-pipeline/`).

- **Pipeline for large multi-task initiatives:** `_inbox/to-analyze/` → `specs/<slug>.md` → `NN-<slug>/plan.md` (tasks `NN.T` sized one-per-commit, inline or expanded) → `done/NN-<slug>/` (with `summary.md`) → `merged/NN-<slug>/`.
- **Emergent tasks (`<category>/T###-<slug>`): Capture first, then continue.** Work that appears mid-session becomes a task file at once; it does not stay in the session context.
- **Ids:** `T###`, unique across `done/` too; reserve the id by creating the file immediately.
- **Layout:** `tasks/<category>/T###-<slug>.md` for small tasks; `T###-<slug>/{README,CONTEXT,PROGRESS}.md` when there is context. Each category has a `README.md` and `notes/`.
- **Header (closed set, exact order):** `id`, `title`, `category`, `priority` (P0-P3), `priority-reason`, `next-up`, `state`, `executor`, `depends-on`, `decider`, `sources`, `paths`, `handoff`. Optional extensions: `profile`, `verification-mode`, `verifier`.
- **States:** `open`, `in progress`, `waiting`, `blocked`, `delivered`, `bounced`, `verified`, `done` (or `done with a caveat`), `dropped`. `verified` is set by someone other than the executor, or by the executor after the owner's explicit approval (recorded in `PROGRESS.md`).
- **Registry:** `00-INDEX.md` (Initiatives, Specs, Next up <= 5, Tasks by category, Decisions waiting, Done) is the state; keep it current with every change.
- **Done:** `git mv` the finished emergent task to `tasks/done/<category>/`.
- **Several sessions:** only a category's `owner-session` edits its tasks; others add notes or new tasks.
