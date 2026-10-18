# T022 Run engine fixes found by the 07.5/12.1 live capture

- id: T022
- title: Run engine fixes found by the 07.5/12.1 live capture
- category: server-and-bindings
- priority: P1
- priority-reason: One can delete another run's worktree; others leave tasks stuck or run in empty dirs
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: scripts/orchestration_runs.py, scripts/test_orchestration_runs.py
- handoff: Read tasks/server-and-bindings/T022-run-engine-fixes-found-by-the-07-5-12-1-live-captu.md, do the open steps, run the Verification, update the task and the registry.
- short: Run engine fixes

verification pending: run Verification checks (independent verifier)

## Goal

Fix the engine problems listed in tasks/12-events-and-triggers/notes/12.1-resumption-facts.md: (1) run cancel must also stop Kilo's tool child processes; (2) continuing a verify run or a run whose worktree was removed must be refused, not run in an empty dir; (3) a verify run must only remove worktrees it created; (4) the supervisor's in-progress transition must not leave the target repo dirty (second execute refused); (5) a failed execute run must let the task go back to open/bounced with a reason; (6) document/handle that a Kilo session resumes only from its original repo; (7) a verify run without --profile must use the configured profile/routing, never silently fall back to built-in expensive models (and Kilo must stay on gemini-3.8-flash).

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
