# N091 tasks close: dry-run skips guards, a failed close leaves the task half-advanced; --actor ignored

- id: N091
- title: tasks close: dry-run skips guards, a failed close leaves the task half-advanced; --actor ignored
- kind: bug
- status: ready
- created: 2026-11-04T14:54:39.762469+00:00
- author: gcube_atlas
- about: tasks_engine.py close
- produced: -
- processed-by: -
- short: close not atomic, actor ignored

Validation of T035 from gcube_atlas (N002), 2026-11-04, on a throwaway copy of gcube_atlas/tasks.
1) 'tasks close T006 --verifier owner --reason ... --dry-run' printed 'Would close T006: open -> in progress -> delivered -> verified -> done', but the real close then failed at 'delivered' (## Steps still had the template placeholder) and left T006 in 'in progress' with a Log line. Expected: dry-run runs the same guards as the real path, and a failing close changes nothing (all-or-nothing).
2) '--actor claude-atlas' was ignored: the Log attributes 'open -> in progress' and 'in progress -> delivered' to the executor (kilo), and 'delivered -> verified' / 'verified -> done' to the verifier. Expected: the actor is recorded for the steps it performs.
What works: verifier: header and verifier/reason in ## Log, for both 'close' and step-by-step 'transition'. 'tasks validate' ok afterwards.

---
- Author: gcube_atlas
- Workspace: /Users/Alfredo/works/gcube_atlas
- ai-orch: 1.1.0 (8e3443a)
- Date: 2026-11-04 14:54:39 UTC
