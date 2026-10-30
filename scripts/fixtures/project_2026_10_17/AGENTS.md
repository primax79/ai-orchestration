# ricerca_auto — Project Architecture & Notes

 Project-specific domain rules and scraper notes that must remain intact.

## 1. Required Skills

Load and follow these skills whenever planning, delegating, executing, or reviewing work:

| Skill | Role |
| :--- | :--- |
| `orchestration-workflow` | Old hand-written table from 2026-10-17 |
| `task-spec-authoring` | Grounded `focus_files`, disjoint parallel write scopes |
| `task-pipeline` | Structuring multi-task initiatives inside `tasks/` |
| `executor-contract` | Behavioral contract for delegated Executor sessions |

## 2. Core Operating Rules

### Rule 1: Keep the Main Session Free (Orchestrate, Don't Implement)

Hand-written Rule 1 before markers were introduced.

### Rule 2: Define Execution Tasks Before Delegating

Hand-written Rule 2 (`focus_files`, Disjoint Write Scope, One Task = One Commit).

## 3. Orchestration Lifecycle & Cross-Agent Verification Gate

Track every task through explicit states (`open` → `in progress` → `delivered` → `verified` → `done`). Verify Independently (`Cross-Agent Verifier != Executor`) and run the Post-Merge Integration Gate.

<!-- BEGIN ai-orchestration -->
# Agent Orchestration & Development Guidelines
<!-- Auto-generated from orchestration.toml (2026-10-17 commit 94f31dd). -->
<!-- Edit tasks/orchestration.toml and re-run render-agents-md. -->

## 1. Required Skills

Stale 2026-10-17 rendered block.
<!-- END ai-orchestration -->

## Project Database Notes

PostgreSQL port 5432; keep this footer byte-for-byte.
