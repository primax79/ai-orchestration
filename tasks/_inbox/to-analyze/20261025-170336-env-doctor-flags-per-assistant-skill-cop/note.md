# N063 Env doctor flags per-assistant skill copies (~/.claude/skills + ~/.kilo/skills) as duplicates to remove

- id: N063
- title: Env doctor flags per-assistant skill copies (~/.claude/skills + ~/.kilo/skills) as duplicates to remove
- kind: bug
- status: ready
- created: 2026-10-25T17:03:36.216983+00:00
- author: ai-coding-tools
- about: -
- produced: -
- processed-by: -
- short: Env doctor flags per-assistant

Owner report 2026-10-25 (screenshot of the doctor UI): ADVICE 'duplicate-name: orchestration-metrics / orchestration-setup / pdf / task-pipeline / task-spec-authoring ...: duplicate standalone skill across origins (standalone:~/.claude/skills, standalone:~/.kilo/skills): review and remove one manually'. Owner: these are not duplicates.

Root cause: scripts/orchestration_env.py ~4230-4255 (advise branch) groups by skill name across origins for assistant kilo. Kilo does load ~/.claude/skills (Claude Code compatibility, on unless KILO_DISABLE_CLAUDE_CODE(_SKILLS) or KILO_DISABLE_EXTERNAL_SKILLS is set or a claude-migration.json receipt exists; references/kilocode/kilocode/packages/opencode/src/skill/index.ts:202-235), but it scans ~/.claude and ~/.agents BEFORE its own config dirs and the last skill with a name wins (index.ts:143-159, it only logs 'duplicate skill name'). So the ~/.kilo copy shadows the ~/.claude copy by design, and each copy is the binding for its own assistant. Removing either one breaks an assistant.

Expected: a name present in ~/.claude/skills (Claude's install) and ~/.kilo/skills (Kilo's install) is not a conflict. At most an INFO 'Kilo also sees the Claude copy; its own ~/.kilo copy wins' when the two differ, optionally suggesting KILO_DISABLE_CLAUDE_CODE_SKILLS=true (with the caveat that Claude-only skills would disappear from Kilo). Keep real conflicts: two copies inside the same assistant's own roots (e.g. ~/.kilo/skills and ~/.config/kilo/skills, or project vs global with differing content). Add a test with identical-name skills in ~/.claude/skills and ~/.kilo/skills: no advise item.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (aed1caa)
- Date: 2026-10-25 17:03:36 UTC
