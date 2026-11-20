# N102 Field evaluation of Gemini 4 Carbon (reviewer) and Neon (executor), 2026-11-20

- id: N102
- title: Field evaluation of Gemini 4 Carbon (reviewer) and Neon (executor), 2026-11-20
- kind: note
- status: ready
- created: 2026-11-20T19:05:19.448803+00:00
- author: aai-workgroup
- about: docs/09-gemini-4-model-selection.md; gemini-4-carbon; gemini-4-neon
- produced: -
- processed-by: -
- short: Field evaluation Gemini 4

Field evaluation of two Gemini 4 models on 2026-11-20 (AAI Workgroup session; Kilo CLI, variant high), for
docs/09-gemini-4-model-selection.md. Same tasks were given in parallel to OpenAI (Codex) and Anthropic (Claude agent),
so the comparison is like for like.

## Gemini 4 Carbon as independent reviewer (2 runs)

| Run | Task | Findings | Unique and valid | False positives | Time | Report size |
| --- | --- | --- | --- | --- | --- | --- |
| T026 | blind security/correctness review of a Keycloak SPI module (~1300 LOC) | 23 (5 high, 14 medium, 4 low) | 2 (disabled context clients emit entitlements; mapper relies on UI-only defaults) | none found | ~21 min | 85 KB (OpenAI 31 KB, Anthropic 31 KB) |
| T027 | review of a 190-requirement specification against ~300 source files | 18 (9 high) | 4 (scopes registered at the IdP differ from requested; identifier may arrive as a 1-element array; known DEBUG token leak means a requirement is not met; mixed MUST/SHOULD rows) | none found | ~34 min | 59 KB (OpenAI 14 KB, Anthropic 31 KB) |

- Strengths: the most thorough on sources (opened every presentation and prior review), systematic arithmetic and
  traceability checks, precise line references.
- Weaknesses: inflates severity (half of its findings "high" where the other two reviewers rated the same issues
  medium); slowest (about 5x Claude on the document review) and most verbose (2-3x report size).
- Recommendation: use as one of several parallel reviewers; recalibrate its severities when used alone.

## Gemini 4 Neon as executor (1 run + 1 follow-up)

- Task: fix 30 specified defects of the same module in 7 prescribed commits, offline unit tests, build on Keycloak
  26.7.5 and 26.8.2; follow-up: wildcard caller list, mirror-client exclusion, audit line.
- Result: ~26 min for the 7 commits, ~6 min for the follow-up; exact commit order and messages; restricted brief folder
  never committed; no push; test secrets replaced (respected the gitleaks hook); 33 then 36 tests green on both Keycloak
  versions (re-run independently); final report accurate per defect id; used Maven offline (-o) on its own initiative.
- Code read so far (critical paths): clean structure, immutable validated configuration, consistent fail-closed
  behaviour, no PII in logs; full diff (~3600 added lines) still under owner review.
- Not yet observed: behaviour on an ambiguous specification.

## Tooling issues met (separate notes)

N100 (kilo_implement ignores working_directory), N101 (installed kilo-mcp lacks 'variant').
