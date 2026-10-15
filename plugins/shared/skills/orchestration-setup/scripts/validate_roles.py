#!/usr/bin/env python3
"""Deterministic half of role-setup verification.

Two independent groups of checks — see ../SKILL.md "Verification" and
"Companion script" sections for the reasoning:

1. Kit-internal (always run, no dependency on the operator's roles.toml):
   every skill in a plugin declares a valid profile in skill-requirements.json,
   and nothing declares a model.
2. Operator-config (only when --roles-file is given and exists): all four
   roles populated, host/model non-empty, effort valid for the pinned model,
   and `basis` (if set) is a known evidence-basis slug.

Exit code is non-zero if any check fails, so this can gate a pre-commit hook.
"""
import argparse
import json
import pathlib
import re
import sys

PROFILES = {'deep-reasoning', 'orchestration', 'bulk-execution', 'exploration'}

# Order of preference from SKILL.md "Guided flow" > "Ranking" — the evidence a tier
# assignment can rest on. `basis` itself is optional; when present it must be one of
# these, so a typo'd or invented value doesn't pass silently.
BASIS_VALUES = {'host-metadata', 'provider-tier-naming', 'model-self-knowledge', 'operator-stated'}

# Best-effort, not authoritative: models known NOT to support `xhigh` effort,
# matched by substring against the model/tier string in roles.toml. Silently
# skipped for anything not listed here — degrade gracefully rather than fail
# closed on a model id this table doesn't know about yet.
KNOWN_NO_XHIGH_SUBSTRINGS = ('opus-4.6', 'sonnet-4.6', 'opus 4.6', 'sonnet 4.6')

FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---\n?', re.DOTALL)


def fail(msg):
    print(f'[FAIL] {msg}')
    return False


def check_kit_internal(plugin_dir):
    ok = True
    skills_dir = plugin_dir / 'skills'
    req_path = plugin_dir / 'skill-requirements.json'
    requirements = {}
    if req_path.exists():
        requirements = json.loads(req_path.read_text())
    elif skills_dir.is_dir() and any(skills_dir.glob('*/SKILL.md')):
        ok = fail(f"{plugin_dir}: has skills but no skill-requirements.json")

    for skill_md in sorted(skills_dir.glob('*/SKILL.md')) if skills_dir.is_dir() else []:
        name = skill_md.parent.name
        entry = requirements.get(name)
        if entry is None:
            ok = fail(f"{plugin_dir}: '{name}' has no skill-requirements.json entry")
            continue
        if entry.get('profile') not in PROFILES:
            ok = fail(f"{plugin_dir}: '{name}' has invalid profile {entry.get('profile')!r} "
                      f"(must be one of {sorted(PROFILES)})")
        if not entry.get('reason', '').strip():
            ok = fail(f"{plugin_dir}: '{name}' skill-requirements.json entry has no reason")
        if 'model' in entry:
            ok = fail(f"{plugin_dir}: '{name}' skill-requirements.json declares a model "
                      f"({entry['model']!r}) — profiles only, never a model")

        text = skill_md.read_text()
        m = FRONTMATTER_RE.match(text)
        if m and re.search(r'^model\s*:', m.group(1), re.MULTILINE):
            ok = fail(f"{plugin_dir}: '{name}/SKILL.md' frontmatter declares a model — "
                      f"the pattern must stay vendor-agnostic")
    return ok


# ---------- tiny flat TOML reader for roles.toml's known shape ----------
# roles.toml only ever has [roles.<profile>] sections with quoted string
# values (plus an optional trailing comment), so a hand-rolled reader avoids
# a tomllib/tomli dependency on Python < 3.11 (this repo doesn't otherwise
# need one).

def read_roles_toml(path):
    roles = {}
    current = None
    section_re = re.compile(r'^\[roles\.([a-z-]+)\]$')
    kv_re = re.compile(r'^([a-zA-Z_]+)\s*=\s*"([^"]*)"\s*(?:#.*)?$')
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        m = section_re.match(line)
        if m:
            current = m.group(1)
            roles[current] = {}
            continue
        m = kv_re.match(line)
        if m and current is not None:
            roles[current][m.group(1)] = m.group(2)
    return roles


def check_operator_config(roles_file):
    ok = True
    roles = read_roles_toml(roles_file)
    for profile in sorted(PROFILES):
        entry = roles.get(profile)
        if not entry:
            ok = fail(f"{roles_file}: role '{profile}' is not populated")
            continue
        if not entry.get('host', '').strip():
            ok = fail(f"{roles_file}: role '{profile}' has no host")
        if not entry.get('model', '').strip():
            ok = fail(f"{roles_file}: role '{profile}' has no model")
        effort = entry.get('effort', '')
        model = entry.get('model', '')
        if effort == 'xhigh' and any(s in model.lower() for s in KNOWN_NO_XHIGH_SUBSTRINGS):
            ok = fail(f"{roles_file}: role '{profile}' pins effort=xhigh on {model!r}, "
                      f"which is known not to support it — silently degrades to a lower effort")
        basis = entry.get('basis')
        if basis and basis not in BASIS_VALUES:
            ok = fail(f"{roles_file}: role '{profile}' has invalid basis {basis!r} "
                      f"(must be one of {sorted(BASIS_VALUES)}, or omitted)")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--plugin-dir', action='append', default=[], type=pathlib.Path,
                     help='Plugin directory containing skills/ and skill-requirements.json; repeatable')
    ap.add_argument('--roles-file', type=pathlib.Path, default=None,
                     help='Path to roles.toml; operator-config checks run only if given and it exists')
    args = ap.parse_args()

    ok = True
    for plugin_dir in args.plugin_dir:
        ok = check_kit_internal(plugin_dir) and ok

    if args.roles_file and args.roles_file.exists():
        ok = check_operator_config(args.roles_file) and ok
    elif args.roles_file:
        print(f"[skip] {args.roles_file} not found — run the interactive-role-setup skill first")

    if ok:
        print('[ok] role validation passed')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
