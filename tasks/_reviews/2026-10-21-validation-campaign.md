# Validation campaign of delivered items (2026-10-21)

Owner rules: delivered items are validated by whoever asked for them or uses them; when nobody uses a feature, Q009
(answer C): the owner validates the web UI and VS Code items by use, ai-coding-tools runs a scripted live check for the
rest and closes them as `done with a caveat: validated by the architect, no user yet`. A user's NOT OK reopens an
item. Durable requests per workspace come with T044 (Durable verification requests); until then this file is the list.

Record each result with `ai-orch tasks transition <id> verified --verifier <who> --reason "<what was checked>"`, then
`done`. NOT OK goes to an inbox note and the item is bounced.

## Done so far

- Requester-validated and closed: T031, T034 (ai-orchestration); T016, T017, T006 (ai-coding-tools); 16.1, 16.3, 16.9,
  10.6, 11.3, 13.6, T019 (by d4science-python-library-2e).
- NOT OK, bounced: 16.5 (Broker MCP tools) -> T045 (Broker validation follow-ups).

## Owner: web UI and VS Code items (Q009, C)

Open the web UI (`ai-orchestration-ui/start.sh`, or the VS Code extension 0.6.0 dashboard) on a workspace with tasks,
use each feature once, and say OK / NOT OK per item. Each item's Verification section says what to look at.

- Web UI: 09.9 (Attachments UI), 10.2 (Timeline tab), 10.5 (Microtask UI), 12.6 (Event streams UI), 12.8 (Orchestrator
  chat), 12.10 (Orchestrator Config card), 12.16 (UI proposal confirm).
- VS Code: 06.9 (VS Code bridge completion), 07.9 (VS Code run handlers), 08.5 (VS Code Decisions tree), 08.7 (Question
  toasts), 09.6 (VS Code inbox parity), 09.11 (VS Code attachments parity), 10.3 (VS Code Timeline), 12.7 (VS Code event
  watcher), 12.15 (VS Code 12.6 parity), 12.17 (VS Code chat parity), T023 (VS Code tree parity).

## Sessions that use the feature (requests lost when the session closed; resend when it is back)

- d4science-evolution-assurance (questions, inbox, conditions, verification): 08.6 (Answer and resume), 09.10
  (Editable triage proposals), 11.4 (Closed-apart placement), T025 (Short title field), T029 (Letter-suffix plan ids),
  T030 (Conditional done), 16.2 (Shared locks and idempotency), 16.4 (Qualified refs and coordination), T033 (Test
  config isolation).
- gcube-audit and d4science-evolution-assurance, after their kilo-mcp restart: ai-coding-tools T018 (Kilo results and
  completion), T019 (Per-workspace Kilo model), T020 (Kilo worktree hygiene).

## ai-coding-tools: scripted live check, no user yet (Q009, A part)

Runs, headless orchestrator, triggers, Doctor and skill installation have no user session today (gcube-audit answered
CANNOT VALIDATE for all of them): 07.5 (Live CLI capture), 07.11 (Microtask batch runs), 12.1 (Headless resumption
facts), 12.5 (Headless orchestrator role), 12.9 (Orchestrator reassignment), 13.2 (Severity and acknowledge), 13.3
(Duplicate resolution), 13.5 (Legacy install classification), 13.7 (Stray files and MCP), T016 (Doctor findings study),
T017 (Remove project skill copies), T018 (Orchestration skill precedence), T021 (Binding template drift), T022 (Run
engine fixes), T026 (Trigger enqueue race), T027 (Duplicate turn resumption), T028 (Unattended turn hardening); and the
backend parts of the inbox and proposals: 09.4 (Agent triage), 09.5 (Process-with review), 09.8 (Attachment
endpoints), T024 (Proposal confirm engine). Tracked as T047 (Architect verification without users).
