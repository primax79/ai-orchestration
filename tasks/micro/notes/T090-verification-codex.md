# T090 verification (Codex, 2026-10-31): BOUNCE

Verified on executor commit 7fe887f, which is merged into `integration/19`. In normal operation the predicate is reused, and there are tests for an unmodified block, for an edited block (preserved byte for byte and reported), and for the rest of the upgrade.

- **B1 (high)**: `plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py:959-977`. When `orchestration_config` cannot be imported (standalone `tasks upgrade`), the fallback defines a SECOND local matching predicate, which can let the managed block be overwritten. Fix: when the authoritative predicate cannot be imported, keep the block and report it for manual review. Add an isolated test, with the module not importable, that proves `tasks/AGENTS.md` is kept byte for byte and reported while the other files are still upgraded.
