# T014 One backend test failed once in eleven runs

- id: T014
- title: One backend test failed once in eleven runs
- category: micro
- priority: P2
- priority-reason: A flaky test hides real regressions and trains people to re-run instead of reading failures
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: architect review of 09.2 (2026-10-17): the first run after rebase reported "1 failed, 34 passed"; ten further runs were green and the failing test name was not captured
- paths: ../ai-orchestration-ui/backend/test_server.py
- handoff: Read tasks/micro/T014-flaky-backend-test.md and fix it.

## Goal

Find and fix the timing-dependent test in `backend/test_server.py`. The likely candidates are the watcher broadcast within 2 s, the slow-CLI concurrency test, and the process-group cleanup tests, which ran while four Kilo tasks loaded the machine.

## Steps

1. Run the suite in a loop under CPU load (for example 4 parallel `yes > /dev/null`), with `-rf -x`, until it fails. Record which test failed.
2. Replace fixed sleeps or deadlines with polling up to a generous timeout, or make the code under test deterministic.

## Verification

Fifty consecutive runs under load are green.
