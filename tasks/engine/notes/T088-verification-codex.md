# T088 verification (Codex, 2026-10-30): BOUNCE

Verified on `integration/19` (executor commit 21bffb2). The process/zombie fixes are correct, including the macOS `ps` flags, and no test was weakened.

- **B1 (high)**: `scripts/orchestration_env.py:612-642`. The stdlib YAML fallback treats folded and literal scalars the same and silently drops nested structures beyond one level (for example a `tags:` list under `metadata:`). Two different skills can then normalize as equal and be trashed automatically. Fix: parse with indentation awareness, or fail closed (never "equal"/fixable) on unsupported YAML. Add negative tests for nested lists and literal versus folded scalars.
- **B2 (medium)**: the executor edited its own task file, which the brief forbids. The integration branch already keeps the authoritative text; do not do it again.
