# UC036 - Architect links tasks to Redmine issues and synchronizes progress

- id: UC036
- title: Architect links tasks to Redmine issues and synchronizes progress
- actor: Architect session
- approval: proposed
- priority: P2
- linked-tasks: -
- verification-type: code-audit
- last-tested: -
- last-verdict: -
- short: Sync Redmine tracker links

## Description & Business Value
Links task nodes to external Redmine issues with typed relations (implements, updates, verifies, under, cites), assigns stable hybrid projections (issue | line | none), and builds hash-verified synchronization plans with preflight safety checks (not implemented yet; spec is draft 2). Source: tasks/specs/tracker-links.md §3

## Preconditions
- Redmine tracker configuration is present in orchestration.toml and task nodes exist.

## Scenario / Interaction Steps
1. The architect links a task node to a Redmine ticket via ai-orch tasks tickets link <id> redmine:#<num> --relation implements.
2. The architect runs ai-orch tracker plan --mode link|reconcile to preflight issue states and generate a hash-guarded update plan.
3. After owner approval (including sample approval for bulk creates), ai-orch tracker apply --expect-hash executes one PUT per issue updating the generated block and done_ratio.

## Automated Verification Command
```bash
echo 'manual: Spec tracker-links.md is draft 2 (not implemented yet); verify ai-orch tasks tickets link and ai-orch tracker plan/apply once implemented.'
```

## Acceptance Criteria
- [ ] Task nodes store typed ticket references (`redmine:#<id> (<relation>)`) with at most one `under` parent per node.
- [ ] Every mapped node stores a stable `projection` (`issue | line | none`) preserved across `expand`, `collapse`, archive, and move operations.
- [ ] `tracker plan` preflights issue ownership, required custom fields, and disabled fields that a PUT might clear, producing a canonical plan with `plan_hash`.
- [ ] Generated blocks (`<!-- ai-orch:begin <node> --> ... <!-- ai-orch:end -->`) isolate updates per implementing node without overwriting human description prose.

## AI Validation Log

