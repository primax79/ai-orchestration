# N032 Parallel branches assign the same note and task ids

- id: N032
- title: Parallel branches assign the same note and task ids
- kind: bug
- status: processed
- created: 2026-10-21T07:13:44.275968+00:00
- author: ai-coding-tools
- about: tasks_engine.py id allocation; T037
- produced: T037
- processed-by: ai-coding-tools

A Kilo worktree branched before N001-N031 were created on main allocated N001 for a new note; the same happens for T### ids when two branches each run 'tasks new'. After merge both files exist with one id. Related to T037 (Conflict-free task index): ids should come from a source that survives branching (e.g. allocate on merge, or ids that embed something unique), or validate should catch duplicates and offer a renumber.
