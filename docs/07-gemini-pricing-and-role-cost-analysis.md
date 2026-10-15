# Report: Cross-Model Pricing Analysis & Multi-Framework Cost Optimization (Gemini vs. Claude vs. Codex)

> **Author:** Kilo Code (AI Orchestrator)  
> **Date:** 2026-10-15  
> **Target Systems:** `ai-orchestration`, `kilo-mcp`, `claude-mcp`, Kilo Code (`~/.config/kilo/kilo.jsonc`), Claude Code (`valutazione modelli claude.md`), Codex CLI  
> **Source Documents Analyzed & Cross-Referenced:**
> - [Google AI Studio — Gemini API Official Pricing (`ai.google.dev/gemini-api/docs/pricing`)](https://ai.google.dev/gemini-api/docs/pricing)
> - [Anthropic Claude Official API Pricing (`anthropic.com/pricing`)](https://www.anthropic.com/pricing)
> - OpenAI API Pricing (`openai.com/api/pricing/`)
> - **Empirical Production Accounting:** [`/Users/Alfredo/works/gcube_audit/docs/reports/COST-AND-ORCHESTRATION-ECONOMICS.md`](/Users/Alfredo/works/gcube_audit/docs/reports/COST-AND-ORCHESTRATION-ECONOMICS.md) (573 real production runs in `kilo.db`, $532 shadow spend)
> - **Claude Model & Effort Operational Handbook:** [`/Users/Alfredo/works/ai-coding-tools/valutazione modelli claude.md`](/Users/Alfredo/works/ai-coding-tools/valutazione modelli claude.md) (Opus / Sonnet / Haiku effort calibration, quota mechanics, `opusplan`, context caching rules)
> - Kilo Code Runtime Configuration (`~/.config/kilo/kilo.jsonc`)

---

## 1. Executive Summary: The Cross-Ecosystem Landscape

In an agentic workflow, cost is not determined by the token price of a single question, but by **the compounding effect of multi-turn tool loops, cumulative context accumulation (30k–200k tokens per turn), prompt cache hit rates, and the cognitive tier chosen for each task**.

By cross-referencing **Google Gemini API rate cards**, **Anthropic Claude API pricing**, and **real-world production metrics from 573 audit runs ($532 total shadow spend)**, this report establishes the comprehensive economic comparison across the three major coding agent frameworks:

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                       CROSS-ECOSYSTEM PRICING RATIOS (Per 1M Tokens)                        │
│                                                                                             │
│  FLAGSHIP DEEP-REASONING:                                                                   │
│  • Claude 3 / 3.5 / 4 Opus:  $15.00 in / $75.00 out (Cache Read: $1.50)                     │
│  • Gemini 4 Argon:           $2.00 in  / $10.00 out (Promo) -> $4.00 in / $20.00 out (Cache: $0.10-$0.20)
│  ──► Opus is 3.75× to 7.5× more expensive than Argon! Cache read is 7.5× to 15× more expensive. │
│                                                                                             │
│  BALANCED WORKHORSE / IMPLEMENTATION:                                                       │
│  • Claude 3.5 Sonnet:        $3.00 in / $15.00 out (Cache Read: $0.30)                     │
│  • Gemini 3.8 Flash:         $0.75 in /  $3.75 out (Promo) -> $1.50 in /  $7.50 out (Cache: $0.075-$0.15)
│  ──► Sonnet is 2.0× to 4.0× more expensive than Flash! Cache read is 2× to 4× more expensive.│
│                                                                                             │
│  FAST EXPLORATION & READ-ONLY:                                                              │
│  • Claude 3.5 Haiku:         $0.80 in /  $4.00 out (Cache Read: $0.08)                     │
│  • Gemini 3.8 Flash:         $0.75 in /  $3.75 out (Cache Read: $0.075)                    │
│  ──► Haiku and Flash are near price parity (~$0.75-$0.80 in / $3.75-$4.00 out).             │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Core Takeaways:
1. **The Architecture/Orchestrator Arbitrage:**  
   Running the main Architect session on `Gemini 4 Argon` delivers frontier-tier reasoning (long-decode, deep math, complex architectural decomposition) at **one-quarter to one-seventh of the token cost of `Claude Opus`**.
2. **The Implementation Workhorse Arbitrage:**  
   Delegating bulk implementation to `Gemini 3.8 Flash` via worktrees reduces execution spend by **50% to 75% compared to `Claude Sonnet`**, while providing a 1M token context window.
3. **The Silent Context Re-Read Penalty in Claude Code:**  
   As documented in `valutazione modelli claude.md`, switching models mid-session in Claude Code **invalidates the prompt cache**, forcing the subsequent turn to re-read the entire accumulated conversation without cache discounts. In multi-turn sessions, keeping session prefixes byte-stable and avoiding mid-flight model switches saves 30%–50% of turn cost.
4. **Claude Pro/Team Quota vs. API Credits:**  
   On Claude Pro plans, Sonnet usage is drawn from the 5-hour rolling quota window, but **Opus usage exceeding 200k context requires API usage credits**. Using `ai-orchestration` to delegate execution to Kilo or local worktrees prevents exhausting Claude Pro rolling quotas.

---

## 2. Complete Cross-Provider Pricing Matrix (Per 1 Million Tokens in USD)

| Model & Provider | Input Price (Uncached) | Output Price (incl. Thinking) | Context Cache Read (Hit) | Context Cache Write | Free Tier Available? |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **`Gemini 4 Argon`** (Google) | **$2.00** *(promo)* → **$4.00** *(Dec 2026)* | **$10.00** *(promo)* → **$20.00** *(Dec 2026)* | **$0.10** → **$0.20** | *(Implicit, free)* | ❌ No |
| **`Gemini 3.8 Flash`** (Google) | **$0.75** *(promo)* → **$1.50** *(Jan 2027)* | **$3.75** *(promo)* → **$7.50** *(Jan 2027)* | **$0.075** → **$0.15** | $0.50–$1.00/M/hr (storage) | ✅ Yes *(data trained)* |
| **`Claude 3 / 3.5 Opus`** (Anthropic) | **$15.00** | **$75.00** | **$1.50** | **$18.75** | ❌ No |
| **`Claude 3.5 Sonnet`** (Anthropic) | **$3.00** | **$15.00** | **$0.30** | **$3.75** | ❌ No |
| **`Claude 3.5 Haiku`** (Anthropic) | **$0.80** *(≤128k)* / $1.00 *(>128k)* | **$4.00** *(≤128k)* / $5.00 *(>128k)* | **$0.08** | **$1.00** | ❌ No |
| **`GPT-5-Codex` / `o3`** (OpenAI) | **$5.00**–**$10.00** *(est.)* | **$20.00**–**$40.00** *(est.)* | **$1.25**–**$2.50** | *(Implicit)* | ❌ No |
| **`GPT-5-Codex-Mini` / `o3-mini`** | **$1.10** | **$4.40** | **$0.55** | *(Implicit)* | ❌ No |

---

## 3. Deep-Dive on Claude Models, Quotas & Effort Levels

Derived from `valutazione modelli claude.md` and Anthropic specifications:

### 3.1 The "Silent Failure vs. Immediate Failure" Rule
The governing criterion for model and effort selection is **whether an error is caught by an automated downstream gate**:
- **Silent Failure (Pay for the Frontier Model — Opus 5, effort: `high` / `xhigh`):**  
  Design conversations, architecture reviews, spec authoring (`task-spec-authoring`), diff review, root-cause debugging of elusive bugs, and semantic merge conflicts. A flawed spec generates no compiler error: it gets faithfully implemented into hundreds of lines of wrong code.
- **Immediate / Noisy Failure (Use the Workhorse Model — Sonnet 5, effort: `medium` / `high`):**  
  Feature implementation with clear acceptance criteria, mechanical refactoring (renames, API migrations), orchestration loops (dispatching workers, polling, status tracking). Tests, typecheckers, and linters immediately catch errors at zero human cost.
- **Deterministic / Read-Only (Use the Fast Model — Haiku 4.5, effort: `low`):**  
  Codebase exploration, symbol discovery, caller tracing, post-gate triage ("tests failed → bounce"), commit messages, and changelogs.

### 3.2 Reasoning Effort Levers in Claude Code
- **Effort before Model:** Decreasing effort on an expensive model (e.g. Opus with `low` effort) wastes money: you pay the high token base fee while losing the analytical depth for which the model was chosen. Prefer **Sonnet at full effort (`high`)** over **Opus at crippled effort**.
- **The `ultrathink` Keyword:** Placing `ultrathink` in a prompt requests maximum reasoning depth for that single turn without permanently altering session settings.
- **The `opusplan` Mini-Pattern:** Claude Code's built-in `opusplan` alias uses Opus during planning mode, then automatically downgrades execution turns to Sonnet. `ai-orchestration` generalizes this pattern across multi-agent worktrees and tools.
- **Effort Compatibility:** `xhigh` is supported on Opus 5, but is silently downgraded to `high` on older Opus 4.6 / Sonnet 4.6 versions.

### 3.3 Context Caching in Claude Code
- Claude's prompt caching provides a **90% discount on input reads** ($0.30/M on Sonnet, $1.50/M on Opus) for prompts >1,024 tokens with a 5-minute TTL.
- **The Mid-Session Switch Trap:** Changing models mid-session (`/model`) forces Claude to rebuild the full conversation history uncached, incurring the full fresh input fee across all prior turns.

---

## 4. Empirical Cross-Check: `gcube_audit` Real Production Data

Cross-referencing theoretical pricing against the **$532 measured spend across 573 production runs** in `~/.local/share/kilo/kilo.db`:

### 4.1 Cost per Planning Unit (Review + Refutation per Component)
- **`Gemini 3.8 Flash` Round 1 (55 components):** **~$2.25 / component**
- **`Gemini 4 Argon` Blind Re-run (99 components):** **~$3.86 / component**
- **Hypothetical `Claude 3.5 Sonnet` Projection:** **~$6.50–$9.00 / component**
- **Hypothetical `Claude 3 / 3.5 Opus` Projection:** **~$28.00–$42.00 / component**

In production, **Argon costs ~1.7× Flash** (not the 2.67× list price), because implicit caching already serves **89% of read tokens** at $0.10/M.

### 4.2 Token Class Breakdown (Where the Budget Actually Burns)
Analyzing the $372 Argon spend:
- **Fresh (Uncached) Input:** **47.3% ($176)** — *The dominant cost bottleneck.*
- **Output Tokens:** **23.4% ($87)**
- **Cache-Read Hits:** **19.1% ($71)**
- **Reasoning Tokens:** **10.2% ($38)**

**The Financial Lever:** Trying to push the 89% cache hit rate higher yields diminishing returns. The true financial lever is **reducing duplicate fresh input**:
1. **Byte-stable prompt prefixes:** Placing invariable instructions (grounding rules, methodology) at the very start of prompts ensures Gemini and Claude prompt caches never bust.
2. **Session reuse (`continue_session_id`):** Conducting code review and subsequent refutation/fixes within the same session rather than separate sandboxes prevents re-reading the entire codebase, saving ~$67 per 100 components.

---

## 5. Multi-Framework Role Mapping (`orchestration.toml`)

Translating these economic findings into the canonical mapping across all three frameworks:

```toml
# ~/.config/ai-orchestration/orchestration.toml

[routing]
default_orchestrator = "kilo"    # or "claude"
default_executor = "kilo"
default_profile = "bulk-execution"

# ─────────────────────────────────────────────────────────────────────────────
# 1. KILO CODE (Google Gemini Backed)
# ─────────────────────────────────────────────────────────────────────────────
[tools.kilo.profiles.deep-reasoning]
model = "google/gemini-4-argon"
variant = "high"
basis = "operator-stated"

[tools.kilo.profiles.orchestration]
model = "google/gemini-4-argon"
variant = "medium"
basis = "operator-stated"

[tools.kilo.profiles.bulk-execution]
model = "google/gemini-3.8-flash"
variant = "medium"
basis = "operator-stated"

[tools.kilo.profiles.exploration]
model = "google/gemini-3.8-flash"
variant = "low"
basis = "operator-stated"

# ─────────────────────────────────────────────────────────────────────────────
# 2. CLAUDE CODE (Anthropic Backed)
# ─────────────────────────────────────────────────────────────────────────────
[tools.claude.profiles.deep-reasoning]
model = "opus"
effort = "high"
basis = "operator-stated"

[tools.claude.profiles.orchestration]
model = "sonnet"
effort = "medium"
basis = "operator-stated"

[tools.claude.profiles.bulk-execution]
model = "sonnet"
effort = "high"
basis = "operator-stated"

[tools.claude.profiles.exploration]
model = "haiku"
effort = "low"
basis = "operator-stated"

# ─────────────────────────────────────────────────────────────────────────────
# 3. CODEX CLI (OpenAI Backed)
# ─────────────────────────────────────────────────────────────────────────────
[tools.codex.profiles.deep-reasoning]
model = "gpt-5-codex"
effort = "high"
basis = "operator-stated"

[tools.codex.profiles.orchestration]
model = "gpt-5-codex"
effort = "medium"
basis = "operator-stated"

[tools.codex.profiles.bulk-execution]
model = "gpt-5-codex-mini"
effort = "medium"
basis = "operator-stated"

[tools.codex.profiles.exploration]
model = "gpt-5-codex-mini"
effort = "low"
basis = "operator-stated"
```

---

## 6. How Kilo Code Tracks and Calculates Costs

Kilo computes and logs cost deterministically at each turn through a 3-tier pipeline:

1. **Provider Response Telemetry:**  
   On every API response, the model provider returns exact token counts: `input_tokens`, `output_tokens`, `reasoning_tokens`, `tokens_cache_read`, and `tokens_cache_write`.
2. **Deterministic Formula:**  
   Kilo looks up the model's rate card in its internal catalog:
   $$\text{cost} = \frac{(\text{input} \times \text{in\_rate}) + (\text{output} \times \text{out\_rate}) + (\text{cache\_read} \times \text{cache\_rate}) + (\text{reasoning} \times \text{out\_rate})}{1,000,000}$$
3. **Storage in SQLite (`~/.local/share/kilo/kilo.db`):**  
   - Every individual turn is logged in the `part` table with `type: "step-finish"`:
     ```json
     {"type":"step-finish", "tokens":{"total":12993,"input":12825,"output":88,"reasoning":80,"cache":{"write":0,"read":0}}, "cost":0.01771125}
     ```
   - Total session usage is aggregated into the `session` table (`cost`, `tokens_input`, `tokens_output`, `tokens_reasoning`, `tokens_cache_read`, `tokens_cache_write`).

---

## 7. Strategic Recommendations

1. **Use `Gemini 4 Argon` or `Claude Opus` strictly for the Architect & Verification roles:**  
   The $2.00–$15.00/M input fee is fully justified for design decisions, spec drafting, and independent verification where mistakes compound silently.
2. **Prevent the "Silent Subagent Leak" in Kilo Settings:**  
   In `~/.config/kilo/kilo.jsonc`, explicitly set `"subagent_model": "google/gemini-flash-latest"` and `"compaction": { "model": "google/gemini-flash-latest" }`. Leaving them unset silently defaults background workers to `Gemini 4 Argon`, tripling execution costs.
3. **Turn ON "Hide Prompt-Training Models":**  
   Ensures zero code leakage to public training datasets.
4. **Leverage Cross-Framework Arbitrage in Multi-Framework Mode:**  
   Architect in Claude Code (`opus` / `sonnet`) → Delegate bulk implementation to Kilo CLI (`Gemini 3.8 Flash`) via `kilo-mcp` → Cross-verify with Codex or Claude. This captures the best reasoning intelligence of both ecosystems while paying bulk rates ($0.75/M) for file edits.
5. **Enforce Commit-Triggered Incremental Scans:**  
   Never schedule full repository sweeps on timers. Commit-triggered incremental runs reduce annual token burn by **98%** ($2.3k vs. $128k/yr).
