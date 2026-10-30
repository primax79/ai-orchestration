# T088 verification (Codex, 2026-10-30): BOUNCE

Verified on `integration/19` (executor commit 21bffb2). The process/zombie fixes are correct, including the macOS `ps` flags, and no test was weakened.

- **B1 (high)**: `scripts/orchestration_env.py:612-642`. The stdlib YAML fallback treats folded and literal scalars the same and silently drops nested structures beyond one level (for example a `tags:` list under `metadata:`). Two different skills can then normalize as equal and be trashed automatically. Fix: parse with indentation awareness, or fail closed (never "equal"/fixable) on unsupported YAML. Add negative tests for nested lists and literal versus folded scalars.
- **B2 (medium)**: the executor edited its own task file, which the brief forbids. The integration branch already keeps the authoritative text; do not do it again.

## Round 2 (Codex, 2026-10-30, fix commit 733e3ca): BOUNCE

The nested maps/lists and literal-versus-folded cases are fixed and tested. B2 is fixed.

- **B1 (high, partial)**: `scripts/orchestration_env.py:663,797-807`. Block scalars with an indentation indicator (`|2`, `>1`, `|2-`, `>+3` and so on) are not recognized and are misparsed as plain multiline scalars. In Codex's probe, `description: |2` followed by `  alpha beta` compares equal to `description: "|2 alpha beta"` (`(True, [], False)`). Fix: support indentation indicators, or fail closed (never equal or fixable) on every block-scalar header that is not fully supported. Add negative tests for these headers.

## Round 3 (Codex, 2026-10-30, fix commit 9d45091): BOUNCE

The indentation indicators are fixed and tested (`orchestration_env.py:663-724`, `test_orchestration_env.py:4362-4485`).

- **B1 (high, still open)**: other valid YAML scalars still compare equal despite different semantics.
  - Quotes are stripped without implementing YAML escaping (`:590-594,731-741`): `description: "alpha\nbeta"` (a newline) and `description: 'alpha\nbeta'` (a literal backslash-n) both parse as `alpha\\nbeta`, and the result is "equal".
  - Quoted keys are split at the first colon (`:808-826`): `"a:b": x` and `'"a': 'b": x'` parse the same.

**Required approach (orchestrator, to stop the case-by-case chase):** the stdlib fallback accepts an EXPLICIT, documented subset and FAILS CLOSED on everything else. "Fails closed" means not parseable, so never equal and never fixable.

- **Allowed:**
  - plain unquoted keys `[A-Za-z0-9_-]+`;
  - plain scalars;
  - single-quoted scalars (where only `''` is special);
  - double-quoted scalars WITHOUT any backslash;
  - block scalars `|` / `>` with chomping and indentation indicators (already done);
  - nested block mappings;
  - block sequences of scalars;
  - `#` comments on their own line.
- **Rejected (fail closed):**
  - quoted keys;
  - double-quoted scalars containing `\`;
  - flow collections `{}` / `[]`;
  - anchors, aliases and tags (`&`, `*`, `!`);
  - tabs used as indentation;
  - `---` / `...` inside the frontmatter;
  - complex keys `?`;
  - inline `#` after a value, unless the value is quoted (or reject it);
  - duplicate keys.
- **Tests:** a table-driven test of semantically different pairs that must NEVER compare equal (include Codex's probes and at least one case per rejected construct). The two original baseline tests (reserialized frontmatter, folded description) must stay green.
