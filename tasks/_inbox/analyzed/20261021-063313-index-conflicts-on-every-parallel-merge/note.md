# N002 Index conflicts on every parallel merge

- id: N002
- title: Index conflicts on every parallel merge
- kind: bug
- status: processed
- created: 2026-10-21T06:33:13.204107+00:00
- author: gcube-audit
- about: -
- produced: T037
- processed-by: ai-coding-tools

Generated tasks/00-INDEX.md conflicts whenever 2+ Kilo branches merge (each adds a row, some regenerate the whole index); merges produced duplicate rows, and once a question file was overwritten during resolution. Workaround: tell Kilo 'add ONE row, do not regenerate' plus a dedupe script. Wanted: merge driver, per-task index fragments, or an uncommitted index built on demand. Their top-1 change.
