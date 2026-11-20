# Gemini 4 model selection for orchestration tasks

> **Date:** 2026-11-20. **Supersedes** the Gemini rows of
> [`07-gemini-pricing-and-role-cost-analysis.md`](07-gemini-pricing-and-role-cost-analysis.md)
> (which predates Hydrogen, Neon and Carbon). Re-check when Google ships a new tier or changes prices.

## Decision

| Use | Model (Kilo id) | Thinking variant | Profile |
| --- | --- | --- | --- |
| Routine implementation, tests, mechanical refactors, reviews of small diffs | `google/gemini-4-hydrogen` | `medium` (`high` for multi-file work) | `bulk-execution` |
| Exploration, RAG Q&A, commit messages | `google/gemini-4-hydrogen` | `low` | `exploration` |
| Pure text summarization, compaction | `google/gemini-3.5-flash-lite` | `minimal` | (Kilo `compaction`) |
| Complex or high-risk tasks: subtle bugs, concurrency, security-sensitive edits, specs, independent verification, semantic conflicts | `google/gemini-4-neon` | `high` | `deep-reasoning` |
| Orchestration turns (dispatch, wait, bookkeeping) | `google/gemini-4-neon` | `medium` | `orchestration` |
| Hardest problems, on demand: system architecture, security audits, a bug Neon got stuck on | `google/gemini-4-carbon` | `high` | `deep-reasoning` (override) |
| Legacy, still accepted, not a default | `google/gemini-4-argon`, `google/gemini-3.8-flash` | | |
| Banned (unchanged) | `google/gemini-3.1-pro*`, any `-latest` alias | | |

Why this and not the earlier pair (3.8 Flash default, 4 Argon complex):

- **Hydrogen replaces 3.8 Flash.** Google names it the default for most projects and the upgrade target for every
  3.x Flash. Vendor Terminal-Bench 4.1: Hydrogen 57% vs 3.8 Flash 18%. Per-token price is double Flash's promotional
  rate until 2026-12-31 and equal from 2027-01-01. Capability gain outweighs one month of price difference.
- **Neon replaces Argon.** From 2026-12-01 Argon costs $4 / $20, the same as Carbon, while Neon costs $3 / $15. Neon
  scores 60 on the AA Intelligence Index (`high`) against Argon's 50 and ranks first on the AA Coding Agent Index
  (58.6 vs 45.5). Hydrogen at `high` (51) already matches Argon at about 40% of its cost per task.
- **Carbon stays on demand.** It ties Neon on the general index and leads on some long-horizon benchmarks, but it is the
  slowest (about 56 tok/s, 37 min per AA task) and the most expensive per coding task (about $9.8 vs $6.9 for Neon).

## Model facts (Google AI Studio, read 2026-11-20)

All four Gemini 4 models: 1,048,576-token context, 65,536 output tokens by default (up to 1M with long decode), text
output only, implicit caching only, function calling, structured output, code execution and Search grounding supported.
Thinking tokens are billed as output.

| Model | Released | Thinking levels | Default | Standard USD per 1M in / out | Cache read | Free tier |
| --- | --- | --- | --- | --- | --- | --- |
| `gemini-4-hydrogen` | 2026-11-12 | low, medium, high, xhigh | high | 1.50 / 7.50 | 0.075 | yes |
| `gemini-4-neon` | 2026-11-18 | low, medium, high, xhigh | high | 3.00 / 15.00 | 0.15 | no |
| `gemini-4-carbon` | 2026-11-10 | low, medium, high | medium | 2.00 / 10.00 until 2026-11-30, then 4.00 / 20.00 | 0.10 → 0.20 | no |
| `gemini-4-argon` | 2026-10-13 | low, medium, high | not stated | 2.00 / 10.00 until 2026-11-30, then 4.00 / 20.00 | 0.10 → 0.20 | no |
| `gemini-3.8-flash` | | | | 0.75 / 3.75 until 2026-12-31, then 1.50 / 7.50 | | yes |
| `gemini-3.5-flash-lite` | | minimal, low, medium, high | minimal | 0.30 / 2.50 | 0.03 | yes |

Batch and Flex halve the standard price; Priority costs 1.8×.

Google's "choosing a model" page: Hydrogen for most new projects (everyday coding, parallel worker agents); Neon for
complex, high-frequency tasks where Hydrogen is not enough; Carbon for the hardest problems (architecture, multi-file
debugging, security audits, when a faster model is stuck); 3.5 Flash-Lite for high-volume text. It suggests tuning the
thinking level before switching model, keeping `xhigh` for hard problems, and a two-step pattern (strong model
diagnoses, Hydrogen implements). Argon is not on that page.

## Independent and vendor benchmarks (approximate, Nov 2026)

| Metric | Hydrogen | Neon | Carbon | Argon | Source |
| --- | --- | --- | --- | --- | --- |
| AA Intelligence Index | 54 xhigh / 51 high / 41 medium | 61 xhigh / 60 high / 55 medium | 60 high | 50 high | AA (independent) |
| AA Coding Agent Index | 52.3 xhigh | 58.6 xhigh | 55.5 high | 45.5 high | AA via Valyu (secondary) |
| Mean cost per coding-agent task | ~$4.45 | ~$6.86 | ~$9.75 | ~$6.84 | AA via Valyu (secondary) |
| Terminal-Bench 4.1 | 57.0% | 65.2% | n/a | n/a | Google (vendor) |
| Output speed | ~165 tok/s | ~101 tok/s | ~56 tok/s | ~66 tok/s | AA |

Caveats:

- Hydrogen and Neon are days old; there is no production track record in our workspaces yet.
- Neon is very verbose (AA: 123M output tokens on the index at `high` vs a class median of 65M) and slow per task.
- Hydrogen's model card mentions hallucinations and occasional timeouts; Google claims about 5× fewer hallucinations
  than 3.8 Flash and better recovery from failed tool calls (vendor claim).
- A request migrated from 3.8 Flash without an explicit variant runs Hydrogen at `high`, raising output cost. Always
  pass the variant.
- Several secondary sources disagree on details (index versions, Argon's thinking levels). Numbers above are the ones
  that agree across sources or come from first-party pages.

## Verification done

`kilo run --model google/gemini-4-{hydrogen,neon,carbon} --variant <v>` answered a trivial prompt through Kilo 7.8.18
on 2026-11-20; all four Gemini 4 ids are in `kilo models`.

## Sources

- Google AI Studio: [models](https://aistudio.google.com/docs/models),
  [choosing a model](https://aistudio.google.com/docs/choosing-a-model),
  [pricing](https://aistudio.google.com/docs/pricing), per-model pages under `docs/models/gemini-4-*`.
- DeepMind model cards: [Hydrogen](https://deepmind.google/models/model-cards/gemini-4-hydrogen/),
  [Neon](https://deepmind.google/models/model-cards/gemini-4-neon/).
- [Artificial Analysis, Gemini 4 Neon](https://artificialanalysis.ai/models/gemini-4-neon).
- [The Decoder: Hydrogen outscores Argon](https://the-decoder.com/googles-gemini-4-hydrogen-outscores-the-bigger-argon-just-four-weeks-after-its-launch/).
- [Valyu: Neon vs Carbon vs Hydrogen vs Argon](https://www.valyu.ai/blogs/gemini-4-neon-vs-carbon-vs-hydrogen-vs-argon).
