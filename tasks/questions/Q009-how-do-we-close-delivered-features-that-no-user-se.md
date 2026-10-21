# Q009 How do we close delivered features that no user session uses, so nobody can validate them by use

- id: Q009
- question: How do we close delivered features that no user session uses, so nobody can validate them by use?
- status: answered
- blocks: -
- decider: owner
- asked-by: ai-coding-tools
- asked: 2026-10-21
- origin-run: -
- open-answer: no
- recommended: C

## Context

Owner rule (2026-10-21): delivered items are validated by the sessions that use the tooling. The first campaign shows that gcube-audit uses only the task engine, kilo-mcp and the inbox, and answered CANNOT VALIDATE for runs (07.5, 07.11), the headless orchestrator (12.1, 12.5, 12.9), Doctor (13.2, 13.3, 13.5, 13.7, T016), orchestration-skill install (T017, T018, T021) and the run engine and triggers (T022, T026-T028). The web UI and VS Code items have the same problem: the sessions work from the terminal. About 40 of the 56 delivered items may have no user.

## Options

- **A** — Architect verification: ai-coding-tools runs a scripted live check per item and closes it as 'done with a caveat: validated by the architect, no user yet'; a user's NOT OK reopens it
- **B** — Keep them delivered until a real user appears; the index shows them as 'awaiting a user'
- **C** — The owner validates the UI and VS Code items by use; A for the rest
- **D** — Review which unused features to keep: deprecate or freeze what no session needs (e.g. headless orchestrator, triggers), and validate only what stays

## Answer

- choice: C
- answered-by: owner
- answered: 2026-10-21
