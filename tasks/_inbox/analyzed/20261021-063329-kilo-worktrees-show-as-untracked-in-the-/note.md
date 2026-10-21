# N021 Kilo worktrees show as untracked in the parent repo

- id: N021
- title: Kilo worktrees show as untracked in the parent repo
- kind: bug
- status: processed
- created: 2026-10-21T06:33:29.550423+00:00
- author: d4science-evolution-assurance
- about: -
- produced: ai-coding-tools:T020
- processed-by: ai-coding-tools

kilo_create_worktree leaves .kilo/worktrees untracked; they added /.kilo/ to .gitignore by hand. Wanted: write .git/info/exclude automatically. Part of their top-3 change.
