# T058 Id collisions across branches and a dangling merge driver

- id: T058
- title: Id collisions across branches and a dangling merge driver
- category: engine
- priority: P2
- priority-reason: Two branches that both run 'tasks new' get the same T###; after merge validate fails and the index keeps one row
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: inbox N032 (folded into T037, not solved there); T037 live check 2026-10-25
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py
- handoff: Read tasks/engine/T058-id-collisions-across-branches-and-a-dangling-merge.md, do the open steps, run the Verification, update the task and the registry.
- short: Branch id collisions

## Goal

After a merge where two branches allocated the same task id, 'ai-orch tasks renumber --dry-run' (or validate's fix hint) proposes the next free id for the later file, rewrites its header, file name and links, and the index regains both rows; validate also warns when the configured merge.ai-orch-index.driver command no longer exists (e.g. a removed worktree path).

## Steps

- [ ] Step 1

## Verification

- Command or check that proves completion
