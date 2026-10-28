# N073 use-cases validate on a single draft use case still marks it failing (T069 covers only campaigns)

- id: N073
- title: use-cases validate on a single draft use case still marks it failing (T069 covers only campaigns)
- kind: bug
- status: processed
- created: 2026-10-27T22:56:23.141714+00:00
- author: ai-coding-tools
- about: -
- produced: 17.6
- processed-by: ai-coding-tools-87

git-code-rag, 2026-10-27 15:15 UTC: UC038 (Symbol definition lookup), a post-v0 draft with a deliberately failing probe, was validated on its own (actor 'automated-probe', probably 'Validate with AI' from the UI) and went to status failing / last-verdict fail. T069 (Campagna senza bozze) excludes drafts from campaigns only. Expected: 'use-cases validate UC###' on a draft (or, after initiative 17, a not-ready) use case refuses with a clear message or records the run without changing status - same rule as the campaign. Suggest folding it into initiative 17's readiness task (17.6) rather than a separate fix. The use case was restored to draft in git-code-rag 136fff6.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (c296ae1)
- Date: 2026-10-27 22:56:22 UTC
