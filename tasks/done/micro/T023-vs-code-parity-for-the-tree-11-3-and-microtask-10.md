# T023 VS Code parity for the Tree (11.3) and microtask (10.5) messages

- id: T023
- title: VS Code parity for the Tree (11.3) and microtask (10.5) messages
- category: micro
- priority: P2
- priority-reason: The webview sends new message types without handlers; the extension release waits for it
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: ../vscode-ai-orchestration/src/views/dashboard-panel.ts
- handoff: Read tasks/micro/T023-vs-code-parity-for-the-tree-11-3-and-microtask-10.md, do the open steps, run the Verification, update the task and the registry.
- verifier: owner
- short: VS Code tree parity

## Goal

Add the extension handlers for every message type the dashboard now sends (tree structure actions, micro create, promote, set-kind, set-labels, labels list) so test-bridge-parity is green, then sync the webview and release the extension.

## Steps
- [x] Implemented per task specification and goal.
## Verification
- [x] Verified by automated test suite and validation checks.
## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done` — Validated by automated test suites and approved by owner for cleanup
- 2026-10-23, owner: state `delivered` -> `verified` — Validated by automated test suites and approved by owner for cleanup
