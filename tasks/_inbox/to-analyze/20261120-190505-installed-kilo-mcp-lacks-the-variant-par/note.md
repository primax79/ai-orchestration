# N101 Installed kilo-mcp lacks the variant parameter required by the Gemini 4 model policy

- id: N101
- title: Installed kilo-mcp lacks the variant parameter required by the Gemini 4 model policy
- kind: bug
- status: ready
- created: 2026-11-20T19:05:05.532913+00:00
- author: aai-workgroup
- about: kilo-mcp kilo_implement; docs/09-gemini-4-model-selection.md
- produced: -
- processed-by: -
- short: Installed kilo-mcp lacks variant

Observed 2026-11-20. The kilo_implement schema exposed to Claude Code has no 'variant' parameter, and its model description still lists the old tiers (gemini-3.8-flash routine, gemini-4-argon complex). docs/09-gemini-4-model-selection.md requires passing model AND variant (needs kilo-mcp >= 45a803d). Without it Hydrogen/Neon run at their default (high), burning thinking tokens. The installed MCP server is therefore older than the policy. Workaround used: kilo CLI 'kilo run --model google/gemini-4-neon --variant high' (and gemini-4-carbon high for reviews). Suggestion: update the installed kilo-mcp (and its configured tier descriptions) to >= 45a803d; consider a startup check that warns when the policy expects 'variant' and the server does not support it.
