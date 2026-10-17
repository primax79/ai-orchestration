#!/usr/bin/env python3
"""regenerate_generic_skills.py - regenerates this repo's own SKILL.md files
from their SKILL.template.md sources (no binding map: template defaults
everywhere). Frontmatter name/description come from the *current* committed
SKILL.md on a fresh run (so this script has nowhere new to invent them from);
pass --check to just verify no drift.

Usage:
  python3 scripts/regenerate_generic_skills.py [--check]
"""
import argparse
import re
import subprocess
import sys
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / 'plugins'
GENERATOR = REPO_ROOT / 'scripts' / 'generate_binding.py'

TEMPLATES = (
    ('plugins/architect-side/skills/orchestration-workflow/SKILL.template.md', 'orchestration-workflow'),
    ('plugins/architect-side/skills/orchestration-metrics/SKILL.template.md', 'orchestration-metrics'),
    ('plugins/architect-side/skills/conflict-resolver/SKILL.template.md', 'conflict-resolver'),
    ('plugins/executor-side/skills/executor-contract/SKILL.template.md', 'executor-contract'),
)

GENERIC_DESCRIPTIONS = {
    'orchestration-workflow': (
        'Orchestrate an Executor agent through the Architect/Executor pattern - '
        'discovery-first exploration, isolation before delegating, non-blocking parallel delegation, '
        'complexity-scaled monitoring/intervention, real verification, defect telemetry, and capture '
        'of emergent tasks. Use for native subagent/worktree orchestration or multi-framework '
        'pipelines. When delegating specifically to Kilo via kilo-mcp tools, prefer kilo-mcp-orchestrator.'
    ),
}

FRONTMATTER_RE = re.compile(r'^---\nname:\s*(.+?)\ndescription:\s*(.+?)\n---', re.DOTALL)


def read_current_frontmatter(skill_md):
    text = skill_md.read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, None
    name = m.group(1).strip()
    description = m.group(2).strip()
    if description.startswith('"') and description.endswith('"'):
        description = description[1:-1]
    elif description.startswith("'") and description.endswith("'"):
        description = description[1:-1]
    return name, description


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()

    failures = 0
    ran = 0
    for rel_template, default_name in TEMPLATES:
        template = REPO_ROOT / rel_template
        skill_dir = template.parent
        out_path = skill_dir / 'SKILL.md'
        _, current_description = read_current_frontmatter(out_path)
        name = default_name
        description = GENERIC_DESCRIPTIONS.get(name, current_description)
        if not description:
            print(f"[FAIL] {out_path}: couldn't read current name/description to seed the generic pass")
            failures += 1
            continue

        cmd = [sys.executable, str(GENERATOR), '--template', str(template),
               '--generic-name', name, '--generic-description', description,
               '--out', str(out_path)]
        if args.check:
            cmd.append('--check')

        result = subprocess.run(cmd)
        ran += 1
        if result.returncode != 0:
            failures += 1

    verb = 'Checked' if args.check else 'Regenerated'
    print(f"\n{verb} {ran} generic skill(s), {failures} failure(s).")
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
