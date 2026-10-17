# 13 - Doctor rework: findings that are true, actionable and resolvable

> **Derived from:** [`../env-doctor/notes/T016-report.md`](../env-doctor/notes/T016-report.md), the evidence-based study of every Doctor finding on the owner's machine (2026-10-17). Each task below is the report's proposal of the same id; read its section in the report first. The `orchestration_env.py` lane runs `13.1 → 13.3 → 13.4 → 13.5 → 13.6 → 13.7`. UI parts follow the frontend lane.
>
> **Owner decisions** from the report are filed as questions Q002–Q005. 13.2 and 13.3 use the answer to Q003 (plugin policy) where it matters.

## Tasks (One Task = One Commit)

### 13.1 - P1-a: stop the no-op "Resolve" loop

- **Status:** `verified` (2026-10-17; claude; live: Doctor shows one Resolve (the single fixable finding) and the rest as advice) · **Size:** S · **Repo:** `ai-orchestration/` + `ai-orchestration-ui/`
- **Goal:**
  - each conflict carries `fixable: true|false`;
  - the UI shows red and "Resolve…" only when the plan contains executable actions;
  - an advice-only plan disables Apply;
  - project scope does not repeat global findings.

### 13.2 - P1-b: severity model, cross-assistant grouping, persistent acknowledge

- **Status:** `open` · **Size:** M
- **Goal:**
  - four severity levels;
  - findings grouped across assistants and scopes;
  - an acknowledge store keyed on content hashes, so a finding returns when a copy changes;
  - unmanaged third-party skills are informational, not amber.

### 13.3 - P1-c: smarter duplicate resolution

- **Status:** `open` · **Size:** M
- **Goal:** Before advising, compare against cached plugin versions, normalized frontmatter and git history of the source repos. Duplicates that are only older or re-serialized become auto-resolvable (5 of the 11 on this machine).

### 13.4 - P1-d: detect stale plugin copies

- **Status:** `done` (2026-10-17; claude; merged into main) · **Size:** S/M
- **Goal:** Report Claude plugin copies that are behind their source, with the commit distance and the unchanged version string.

### 13.5 - P2-a + P2-d: history-aware classification of legacy installs (`outdated-legacy` + "Update")

- **Status:** `in progress` (2026-10-18; claude; kilo, worktree task/13.5-legacy-classification) · **Size:** M
- **Goal:** Pre-receipt copies that match an earlier source commit are `outdated-legacy`, not `foreign`, and the UI offers "Update". Standalone-only duplicates are handled too.

### 13.6 - P2-b + P2-c: Kilo effective view; install respects plugins and policy

- **Status:** `open` · **Size:** M
- **Goal:**
  - a Kilo view covering every folder Kilo reads (including `~/.claude/skills` and `~/.config/kilo/skills`);
  - `install-skills` skips skills that a plugin provides or that the conflict policy would remove, so install and resolve no longer undo each other.

### 13.7 - P3-a..d: stray-file and redundant-MCP actions, `register-mcp` idempotency, agents in the Doctor, trigger-conflict generalization

- **Status:** `open` · **Size:** M
- **Goal:** Report §P3.
