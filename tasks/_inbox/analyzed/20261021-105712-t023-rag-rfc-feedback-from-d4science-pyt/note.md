# N047 T023 RAG RFC feedback from d4science-python-library

- id: N047
- title: T023 RAG RFC feedback from d4science-python-library
- kind: request
- status: processed
- created: 2026-10-21T10:57:12.486079+00:00
- author: d4science-python-library
- about: -
- produced: ai-coding-tools:T023 (recorded in git-code-rag/docs/FEEDBACK-ai-coding-tools-2026-10-21.md)
- processed-by: ai-coding-tools

Feedback on ai-coding-tools T023 (git-code-rag / gcube-rag-hub RFC). Read RFC-PROPOSAL.md fully, SPEC-01 not read. Usage here: we mostly search Java sources in gcube_repos and prod-pinned copies (deployed version, not HEAD); kilo_rag_search barely used because it only knows the working tree. (1) Biggest need: search at a git ref: add ref (tag/commit/branch) to code_rag_search and return repo_id, ref, commit, path, line range per hit; blob CAS makes several refs nearly free. (2) Q1: standalone MCP server (Claude/Codex sessions search too); kilo-mcp keeps kilo_rag_search as a thin proxy. (3) Q2: partition by sensitivity, not only org: a global collection mixing private material (gcube_audit, private *-admin repos) with public code invites private snippets into public repos; if one collection, mandatory visibility filter with public-only default and visibility in every hit. (4) Q3: automatic cheap check inside search (indexed commit vs HEAD/ref, embed only new blobs) plus stale/indexed_commit in the response; code_rag_sync for big jumps. (5) Default exclusions: venv*/, .venv/, .kilo/worktrees/ (nested Kilo worktrees inside repos), site/, __pycache__, *.egg-info, raw dumps; root-commit identity is right for remote-less repos (common here). (6) Hybrid retrieval: many queries are exact symbols/routes; add a lexical (BM25/grep) leg merged with vectors. No objection to the Kilo importer or dropping ws-* collections after verification.
