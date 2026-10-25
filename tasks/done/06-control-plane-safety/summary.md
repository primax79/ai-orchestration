# Summary: 06 - Control-plane safety (Doctor, index, UI backend, VS Code bridge)

- **Shipped:** 2026-10-23
- **Plan:** [`plan.md`](plan.md)
- **Validation:** closed in bulk on 2026-10-23 (verifier: owner; "Validated by automated test suites and approved by owner for cleanup"); items marked "done with a caveat" had no user session to validate them.

## Outcome

Control-plane safety and integrity hardening landed across the Doctor, index sync, UI backend, and VS Code extension bridge. The changes introduced generated-region markers for lossless index synchronization, dry-run plans with content hashing, plugin-aware inventory and real MCP config inspection in the Doctor, authenticated non-blocking UI backend execution, and exclusive task-write locking.

- **06.1** — Lossless `sync-index` with generated-region markers (I1–I4): done
- **06.2** — Doctor: `--dry-run` plans with hash, no-clobber install, trash instead of delete, explicit obsolete cleanup (E4, E6, E7): done
- **06.3** — Doctor: plugin-aware inventory and conflicts (E5): done
- **06.4** — Doctor: MCP registration and status through the real config files (E3): done
- **06.5** — UI backend: auth, non-blocking CLI calls, fixed workspace, watcher (U1, U4, U5, U6): done
- **06.6** — Core: `render-agents-md --diff` with hash precondition: done
- **06.7** — UI backend: preview/apply endpoints; transitions no longer write the index (U2, U3): done
- **06.8** — Frontend: confirmation modal with previews, safer installer defaults, Doctor origins, error banners, WS reconnect (U3, U7, V3): done
- **06.9** — VS Code bridge: complete handler map, non-zero rejection, `dist-webview` sync, no hard-coded paths, multi-root choice (V1, V2): done
- **06.10** — Core: task-write lock, `--expect-task-hash`, atomic writes (A9): done

## Deviations

Amendments after review 2 (A1–A12) expanded the scope of tasks 06.2–06.9 and added task 06.10 for task-write locking and atomic writes. The `set-routing`/`set-profile` `--diff`/`--expect-hash` capability originally slated for 06.6 was transferred to 07.1.

## Follow-ups

None recorded in the plan.
