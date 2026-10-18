# T002 Decision telemetry (`kilo_log_decision`) and ROI analysis rework

- id: T002
- title: Decision telemetry (kilo_log_decision) and ROI analysis rework
- category: server-and-bindings
- priority: P1
- priority-reason: Required to calibrate delegation policy with real observables instead of uncalibrated inline estimates
- next-up: no
- state: done
- executor: self
- depends-on: -
- decider: -
- sources: ../architect-executor-consolidated-review.md (§1.5, §2.4, §3.1, §3.4), docs/02-gap-analysis-and-evolution-roadmap.md
- paths: ../kilo-mcp/server.py, ../kilo-mcp/test_server.py, ../kilo-mcp/kilo-mcp.example.toml, ../ai-architect-executor/plugins/architect-side/skills/delegation-roi-analysis/SKILL.template.md, ../kilo-mcp/bindings/delegation-roi-analysis.json
- handoff: Read tasks/server-and-bindings/T002-decision-telemetry-and-roi-rework.md, do the open steps, run the Verification, update the task and the registry.
- verifier: orchestrator:deep-reasoning
- short: Decision telemetry rework

## Goal

Record the actual orchestration branch taken (`delegate` | `inline` | `escalate` | `discarded`), surface observable quality/cost metrics in `kilo_metrics`, tighten the default `delegation_policy`, and update `delegation-roi-analysis` / `mcp-metrics-analyst`.

## Steps

1. Add `kilo_log_decision(branch, reason, task_ref="", followup_needed=False, run_id="")` to `../kilo-mcp/server.py` persisting to `decisions.jsonl` under `DATA_DIR`.
2. Extend `kilo_metrics` in `../kilo-mcp/server.py` to report decision counts by branch, inline follow-up rate, cancellation rate, and discarded-completed-run rate alongside cost per completed task.
3. Update `delegation_policy` default in `../kilo-mcp/kilo-mcp.example.toml` (explicit inline criteria: single file, <10 lines, no logic/signature change, already in context; plus 2-failure escalation clause).
4. Update `../ai-architect-executor/plugins/architect-side/skills/delegation-roi-analysis/SKILL.template.md` and `../kilo-mcp/bindings/delegation-roi-analysis.json` to include discarded runs, context/quota framing for zero-marginal-cost setups, and observable metrics. Regenerate skills and indices.

## Verification

- `../kilo-mcp/.venv/bin/pytest ../kilo-mcp/test_server.py` passes with tests for `kilo_log_decision` and `kilo_metrics`.
- `python3 ../kilo-mcp/scripts/regenerate_bound_skills.py --check` exits 0.
