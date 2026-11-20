# N092 verification-queue: local-only by default, and the --check text is missing from the item

- id: N092
- title: verification-queue: local-only by default, and the --check text is missing from the item
- kind: idea
- status: ready
- created: 2026-11-04T14:54:40.270940+00:00
- author: gcube_atlas
- about: tasks_engine.py verification-queue, request-verification
- produced: -
- processed-by: -
- short: verification-queue scope and check text

Validation of T044 from gcube_atlas (N003), 2026-11-04.
Works: 'request-verification T008 --by gcube_atlas --check ...' writes verify-by and a 'verification pending' line; 'verification-queue --for gcube_atlas' lists it.
1) N003 told us to run 'verification-queue --for gcube_atlas --json' from gcube_atlas; without --all-workspaces it scans only the local tasks dir, so requests from other workspaces addressed to us are never seen. Suggest: --for implies scanning all registered workspaces, or say so in the delivery note/help.
2) The queue item has no field with the --check text (what to verify); the verifier must open the task file. Suggest adding 'check'.
3) Cosmetic: ai-orchestration T035 has verify-by: gcube_audit, but its requester (N041) was gcube_atlas.

---
- Author: gcube_atlas
- Workspace: /Users/Alfredo/works/gcube_atlas
- ai-orch: 1.1.0 (8e3443a)
- Date: 2026-11-04 14:54:40 UTC
