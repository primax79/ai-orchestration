# N045 Broker errors: hash mismatch has free text in error; items lack project

- id: N045
- title: Broker errors: hash mismatch has free text in error; items lack project
- kind: bug
- status: processed
- created: 2026-10-21T08:30:43.380922+00:00
- author: d4science-python-library
- about: -
- produced: T045
- processed-by: ai-coding-tools

On an expect_hash mismatch the 'error' field holds free text instead of a stable code and 'message' repeats raw CLI JSON (spec 3b: error = kebab-case code). tasks.next and questions.list items lack a project field, while workspace-level tasks.next mixes _workspace tasks.
