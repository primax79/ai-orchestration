# N013 tasks new: --step/--verification; validate rejects placeholders

- id: N013
- title: tasks new: --step/--verification; validate rejects placeholders
- kind: feature
- status: processed
- created: 2026-10-21T06:33:16.502245+00:00
- author: gcube-atlas
- about: -
- produced: T036
- processed-by: ai-coding-tools

new writes placeholder bullets ('Implement task steps.', 'Verify task implementation.') and validate passes them, so an unspecified task looks valid. Wanted: repeatable --step/--verification and a validate error (or warning) on placeholders. Their top-1 change.
