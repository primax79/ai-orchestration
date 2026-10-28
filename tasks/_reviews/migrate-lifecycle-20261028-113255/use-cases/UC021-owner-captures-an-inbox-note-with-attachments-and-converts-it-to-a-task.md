# UC021 - Owner captures an inbox note with attachments and converts to task

- id: UC021
- title: Owner captures an inbox note with attachments and converts to task
- actor: Owner
- status: draft
- priority: P1
- linked-tasks: 09.1, 09.2, 09.3, 09.7, T034
- verification-type: automated-probe
- last-tested: -
- last-verdict: -
- short: Convert inbox note

## Description & Business Value
Allows the owner or an agent session to capture raw bug reports, feature ideas, or tooling feedback in tasks/_inbox/to-analyze/ with content-validated attachments, convert them into emergent tasks preserving attachments, and archive the processed note into _inbox/analyzed/. Source: tasks/specs/inbox-notes.md §3

## Preconditions
- A project tasks/ directory is initialized.

## Scenario / Interaction Steps
1. The owner creates a note via ai-orch inbox add and attaches a screenshot, log, or PDF via ai-orch inbox attach.
2. The owner runs ai-orch tasks new --from-note N### to create a linked emergent task.
3. The engine copies the note attachments into the new task folder and sets sources to N###.
4. Running ai-orch inbox resolve N### moves the note folder to _inbox/analyzed/ with produced set to the new task ID.

## Automated Verification Command
```bash
T=$(mktemp -d) && H=$(./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --json | jq -r .plan_hash) && ./bin/ai-orch tasks upgrade --tasks-dir "$T/tasks" --apply --expect-plan-hash "$H" >/dev/null && echo "Error stacktrace line 1" > "$T/trace.log" && ./bin/ai-orch inbox add --tasks-dir "$T/tasks" --title "Crash on startup" --kind bug --body "App crashes when config is empty." --about "scripts/" --status ready >/dev/null && ./bin/ai-orch inbox attach N001 --tasks-dir "$T/tasks" --file "$T/trace.log" >/dev/null && ./bin/ai-orch tasks new --tasks-dir "$T/tasks" --from-note N001 --title "Fix startup crash" --priority P1 --priority-reason "Crash" --executor kilo --step "Fix empty config handling" --verification "pytest" >/dev/null && ./bin/ai-orch inbox resolve N001 --tasks-dir "$T/tasks" --produced T001 --by owner >/dev/null && test -f "$T/tasks/bugfix/T001-fix-startup-crash/attachments/01-trace.log" && ./bin/ai-orch inbox show N001 --tasks-dir "$T/tasks" --json | jq -e ".note.status == \"processed\" and .note.produced == \"T001\" and .note.in_analyzed == true" >/dev/null && rm -rf "$T"
```

## Acceptance Criteria
- [ ] `ai-orch inbox add` creates `tasks/_inbox/to-analyze/<ts>-<slug>/note.md` with a unique `N###` identifier.
- [ ] `ai-orch inbox attach` validates attachment content (magic bytes for images, UTF-8 without NUL bytes for text, `%PDF-` for PDFs) and size (<=10 MB).
- [ ] `ai-orch tasks new --from-note N###` copies the note attachments into the created task folder, rewrites Markdown links, and sets `sources` to the note.
- [ ] `ai-orch inbox resolve N###` moves the note folder into `tasks/_inbox/analyzed/` and records `produced` and `processed-by`.

## AI Validation Log

