---
name: {{NAME}}
description: "{{DESCRIPTION}}"
---

# {{NAME}}

## Quick Reference

| Field | Value |
| --- | --- |
| **Audience / Role** | Architect / Orchestrator (`deep-reasoning` profile) |
| **When to Load** | Evaluating delegation efficiency, cancellation/bounce rates, and recurring defect patterns |
| **Execution Modes Supported** | **Single-Framework Native** (parallel native worktrees/subagents) and **Multi-Framework MCP / CLI** |
| **Companion Scripts** | `bin/ai-orch` |
| **Related Skills** | `orchestration-workflow`, `task-spec-authoring`, `conflict-resolver` |

{{BLOCK:intro}}This skill guides the Architect in evaluating and reporting delegation
efficiency and defect rates, using whatever telemetry the specific binding
or task history collects. Protocol-agnostic: the questions below apply
regardless of whether tasks were dispatched via Single-Framework Native
worktrees/subagents or Multi-Framework MCP connectors.{{/BLOCK}}

## Logic and Behavior

- **ROI Analysis:** {{BLOCK:roi_analysis}}compare the actual delegation cost against the
  hypothetical cost of generating the same work inline (without
  delegating). Detail savings and efficiency multipliers to the user. Note
  that the real delegation cost includes the Executor's own execution
  cost when the operator pays for its tokens/compute - a "free" Executor
  changes the comparison to Architect-only cost (spec + review).
  - **Empirical Cost Multiplier:** Measured production runs across 573 sessions
    show that flagship reasoning models (`Gemini 4 Argon`, `Claude Opus`) cost
    **~1.7× more per component** than fast agent models (`Gemini 3.8 Flash`,
    `Claude Sonnet`) in multi-turn sessions (dampened from the theoretical 2.7×
    list ratio by implicit context caching).
  - **Token Class Cost Breakdown:** In sustained agent sessions, token spend
    distributes across:
    - **Fresh (Uncached) Input (~47% of cost):** The primary cost bottleneck. Minimized by byte-stable prompt prefixes and reusing sessions (`continue_session_id`) between review and fixes.
    - **Output Tokens (~23% of cost):** Bounded by concise, structured report formats (`Final Report`).
    - **Cache-Read Hits (~19% of cost):** Served at 10× to 20× discount.
    - **Reasoning / Thinking Tokens (~10% of cost):** Essential for deep analysis; avoid running on mechanical tasks.
  - **Online Model Pricing References:**
    - Google Gemini API: [`https://ai.google.dev/gemini-api/docs/pricing`](https://ai.google.dev/gemini-api/docs/pricing)
    - Anthropic Claude API: [`https://www.anthropic.com/pricing`](https://www.anthropic.com/pricing)
    - OpenAI API: [`https://openai.com/api/pricing/`](https://openai.com/api/pricing/)
    - See also the production report in `docs/07-gemini-pricing-and-role-cost-analysis.md`.{{/BLOCK}}
- **Defect Tracking:** {{BLOCK:defect_tracking}}review logged defects found during verification.
  Group them by severity and category to identify patterns.{{/BLOCK}}
- **{{BLOCK:cancelled_label}}Cancelled/aborted runs{{/BLOCK}}:** {{BLOCK:cancelled_runs}}a task stopped mid-flight before completion
  still consumed real resources (the Executor's subprocess ran before
  being killed) and typically has no usable outcome record since no Final
  Report was produced. A high rate of cancellations for a given kind of
  task is itself a signal worth surfacing - it usually means the spec
  needs tighter constraints or the task is a poor fit for delegation.{{/BLOCK}}
- **Feedback Loop:** {{BLOCK:feedback_loop}}if recurring patterns are found (e.g. missed edge
  cases, styling mismatches, frequent cancellations), propose adding
  specific guardrails to future task specifications, or creating targeted
  Executor-side skills to close the gap - see `task-spec-authoring` for how
  task-spec quality itself is the main lever on defect rate.{{/BLOCK}}
