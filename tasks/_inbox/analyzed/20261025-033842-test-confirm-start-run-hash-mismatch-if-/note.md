# N054 test_confirm_start_run_hash_mismatch_if_plan_changed flaky under load

- id: N054
- title: test_confirm_start_run_hash_mismatch_if_plan_changed flaky under load
- kind: bug
- status: processed
- created: 2026-10-25T03:38:42.320303+00:00
- author: ai-coding-tools
- about: -
- produced: T053
- processed-by: ai-coding-tools

Failed once with 'preview_failed' in a full-suite run that took 32 min (machine loaded by many Kilo runs); passes alone 3/3. Likely a timing assumption in the trigger/run preview path. Root-cause and make it deterministic.
