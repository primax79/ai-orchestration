# N038 validate fails on legacy free-text fields in old tasks

- id: N038
- title: validate fails on legacy free-text fields in old tasks
- kind: bug
- status: processed
- created: 2026-10-21T08:16:42.220132+00:00
- author: gcube_audit
- about: -
- produced: T039
- processed-by: ai-coding-tools

validate FAILs on legacy free-text header fields in old tasks; it should warn (as it already does for legacy deciders) and leave old files valid. Source: N035 consultation.
