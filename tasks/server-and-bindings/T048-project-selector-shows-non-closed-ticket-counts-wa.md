# T048 Project selector shows non-closed ticket counts (waiting, open, progress)

- id: T048
- title: Project selector shows non-closed ticket counts (waiting, open, progress)
- category: server-and-bindings
- priority: P1
- priority-reason: With 400+ projects in multi-project workspaces like porting_liferay, users need non-closed ticket counts (waiting, open, progress) next to each project name in the dropdown
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: -
- paths: ../ai-orchestration-ui/frontend/src/components/Navbar.tsx, ../vscode-ai-orchestration/src/extension.ts
- handoff: Read tasks/server-and-bindings/T048-project-selector-shows-non-closed-ticket-counts-wa.md, do the open steps, run the Verification, update the task and the registry.
- short: Project selector active counts

verification pending: run Verification checks (independent verifier)

## Goal

Show total non-closed tickets and the breakdown (waiting, open, progress) next to each project name in the project selector dropdown (and All projects option), sorting active projects to the top after _workspace.

## Steps

- [ ] Implement task steps.

## Verification

- [ ] Verify task implementation.
