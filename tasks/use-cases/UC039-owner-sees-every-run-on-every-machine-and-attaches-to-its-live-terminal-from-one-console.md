# UC039 - Owner sees every run on every machine and attaches to its live terminal from one console

- id: UC039
- title: Owner sees every run on every machine and attaches to its live terminal from one console
- actor: Owner
- approval: proposed
- priority: P1
- linked-tasks: 19.4, 19.5, 19.6, 19.8, 19.9, 19.15, 19.16, 19.18
- verification-type: e2e
- last-tested: -
- last-verdict: -
- short: Multi-host console attach

## Description & Business Value
Development happens in long-lived agent sessions in screen on the Mac and on the hub (alf_ubuntu). The owner needs one place showing runs, tasks by host, questions and deliveries, and a way to open any session's terminal. Source: tasks/specs/multi-machine-development-architecture.md

## Preconditions
Hosts declared in the global config, reachable over ssh; runs started with the screen backend

## Scenario / Interaction Steps
1. Owner runs ai-orch console status --all-hosts on the Mac. 2. It shows runs of both hosts with host, task, state, age and last heartbeat; an unreachable host is shown as such. 3. Owner runs ai-orch console attach <run>. 4. The live screen session of that run opens (shared attach); detaching leaves the agent running.

## Automated Verification Command
```bash
echo 'No verification command specified'
```

## Acceptance Criteria
- [ ] No daemon is required
- [ ] a host that is down never blocks the others
- [ ] another host's run is never marked lost or killed

## AI Validation Log

