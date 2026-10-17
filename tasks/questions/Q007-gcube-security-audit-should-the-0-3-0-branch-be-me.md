# Q007 gcube-security-audit: should the 0.3.0 branch be merged and released so the plugin becomes the canonical copy

- id: Q007
- question: gcube-security-audit: should the 0.3.0 branch be merged and released so the plugin becomes the canonical copy?
- status: open
- blocks: T019 (waiting)
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-18
- origin-run: -
- open-answer: yes
- recommended: A

## Context

The standalone copy (~/.kilo/skills/gcube-security-audit, symlinked in ~/.claude/skills) is 0.3.0: 21 files, two-level audit method, 7 review templates, 7 reference guides, 4 more scripts, stricter rules.json. The plugin (gcube-developer-tools 0.2.1) still ships 0.1.4. The 0.3.0 files are committed in gcube-ai-toolkit on branch skills/security-audit-0.3-d4science-infra, never merged to main. Details: T019-skill-diffs.md section 2.

## Options

- **A** — Merge and release: merge the branch into gcube-ai-toolkit main, bump the plugin, update Claude, remove the standalone copy and symlink
- **B** — Standalone canonical: keep the 0.3.0 standalone copy and leave the plugin at 0.1.4, acknowledged in the Doctor
- **C** — Back to 0.1.4: discard the 0.3.0 work and keep only the plugin version

## Answer

- choice: -
- answered-by: -
- answered: -
