# UC040 - Executors on the Mac and on the hub take tasks from one queue without double claims, and keep working when the hub is down

- id: UC040
- title: Executors on the Mac and on the hub take tasks from one queue without double claims, and keep working when the hub is down
- actor: Orchestrator
- approval: proposed
- priority: P1
- linked-tasks: 19.4, 19.7, 19.10, 19.11, 19.12, 19.13, 19.17
- verification-type: e2e
- last-tested: -
- last-verdict: -
- short: Shared queue across hosts

## Description & Business Value
The owner runs executors on both machines from v1. The hub is the single writer of task state; runs execute anywhere. Project work must not slow down if the hub or the system fails. Source: tasks/specs/multi-machine-development-architecture.md and its review §10

## Preconditions
Project opted in with [multi_host] enabled; hub reachable over ssh from the Mac (except in the offline scenario)

## Scenario / Interaction Steps
1. On the Mac, run start T claims T on the hub (state in progress, host mac, generation g) and the hub commits and pushes. 2. A concurrent claim of T from the hub is refused. 3. The Mac run sends heartbeats to the hub. 4. The executor writes delivered on its branch; the supervisor pushes and calls run ack-delivery; the hub checks generation, commits and Final Report, writes delivered on main and emits run.delivered. 5. With the hub unreachable, run start --offline claims locally and starts at once; on reconnect the claim is pushed, or the owner is asked on conflict.

## Automated Verification Command
```bash
echo 'No verification command specified'
```

## Acceptance Criteria
- [ ] No task is ever claimed by two hosts at once
- [ ] a delivery with a stale generation is refused
- [ ] turning multi_host off needs no migration
- [ ] the manual workflow keeps working

## AI Validation Log

