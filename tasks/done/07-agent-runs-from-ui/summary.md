# Summary: 07 - Agent runs from the control plane (choose who does the work)

- **Shipped:** 2026-10-23
- **Plan:** [`plan.md`](plan.md)
- **Validation:** closed in bulk on 2026-10-23 (verifier: owner; "Validated by automated test suites and approved by owner for cleanup"); items marked "done with a caveat" had no user session to validate them.

## Outcome

End-to-end agent execution and supervision capabilities were integrated into the control plane, CLI, UI, and VS Code bridge. The run engine provides worktree isolation, execution and verification modes, process supervision with clean cancellation, blocking question capture, and configuration editing for routing and tool allow-lists.

- **07.1** — `config set-routing`, surgical TOML updater, `[tools.<t>.headless]` schema, correct project-config path text: done
- **07.2** — Run engine A: registry, locking, records, request validation, prompts, `options`/`preview`/`list`/`show`: done
- **07.3** — Run engine B: supervisor, adapters (prompt via stdin/file), cancel and lost reconciliation with process-group kill: done
- **07.4** — Run engine C: worktree isolation, verify target, verdict parsing and `apply-verdict`, continue invariants, `cleanup`: done
- **07.5** — Live capture with the real CLIs: session ids, Final Report, verdict, continue; flag table correction: done with a caveat: validated by the architect, no user yet
- **07.6** — UI backend: run and config endpoints: done
- **07.7** — Frontend: Run dialog with live preview, task runs panel, Runs tab: done
- **07.8** — Frontend: Config tab editing (routing and profile/model matrix): done
- **07.9** — VS Code: run handlers and run watcher: done
- **07.10** — Core: run supervisor files blocking questions (R14, spec 08 Q8): done
- **07.11** — Batch runs for microtasks: done with a caveat: validated by the architect, no user yet
- **07.12** — Built-in per-mode Claude allow-list (Q001 decision A): done

## Deviations

Amendments after review 2 (R1–R14) expanded tasks 07.1–07.5, 07.8, and 07.9. Question Q001 decision A introduced task 07.12 (built-in per-mode tool allow-lists for Claude), and task 07.11 was added to handle batch execution of microtasks from the timeline specification.

## Follow-ups

None recorded in the plan.
