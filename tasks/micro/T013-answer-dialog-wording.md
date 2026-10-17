# T013 Answer confirmation dialog says "No modifications required"

- id: T013
- title: Answer confirmation dialog says "No modifications required"
- category: micro
- priority: P3
- priority-reason: Cosmetic; the answer is applied correctly
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: architect live check of 08.4 (2026-10-17)
- paths: ../ai-orchestration-ui/frontend/src/components/DecisionsTab.tsx
- handoff: Read tasks/micro/T013-answer-dialog-wording.md and fix it.

## Goal

The confirmation dialog for answering a question shows the reused diff-view text "No modifications required". It should show the chosen option, the free text, and the effect on the blocked tasks (for example "T007 returns to open").

## Steps

1. Pass a summary body instead of an empty diff to ConfirmDialog in the answer flow.

## Verification

The dialog shows the choice and the effect; the answer is still applied.
