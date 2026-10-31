#!/usr/bin/env python3
"""Worktree/branch state for every session directory that is a git worktree (read-only git). Input: TSV from kilo_runs.py.
Output TSV: dir, n_sessions, exists, branch, dirty, default_branch, ahead, merged, last_commit_date,
then (only for unmerged ones) unpushed commits, remote ref present, last subject.
Worktree detection: path contains '/worktrees/' or '-wt-' (override with --marker, repeatable).
Usage: worktree_state.py KILO_RUNS.tsv [--marker S]... [--exclude S]..."""
import sys, csv, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
ap = argparse.ArgumentParser(description=__doc__); ap.add_argument('tsv'); ap.add_argument('--marker', action='append', default=['/worktrees/', '-wt-']); ap.add_argument('--exclude', action='append', default=[])
a = ap.parse_args()
cnt = collections.Counter(r[1] for r in list(csv.reader(open(a.tsv), delimiter='\t'))[1:] if not excluded(r[1], a.exclude))
print('\t'.join(['dir','n_sessions','exists','branch','dirty','default','ahead','merged','last_commit','unpushed','remote_ref','last_subject']))
for d, n in sorted(cnt.items()):
    if not any(m in d for m in a.marker): continue
    if not os.path.isdir(d): print(f"{short(d)}\t{n}\tGONE"); continue
    br = git(d, 'rev-parse', '--abbrev-ref', 'HEAD'); dirty = len(git(d, 'status', '--porcelain').splitlines())
    common = git(d, 'rev-parse', '--git-common-dir'); root = os.path.dirname(os.path.join(d, common)) if common and not common.startswith('/') else os.path.dirname(common)
    default = default_branch(root or d)
    ahead = git(d, 'rev-list', '--count', f'{default}..HEAD') if default else '?'
    merged = 'yes' if default and git_ok(d, 'merge-base', '--is-ancestor', 'HEAD', default) else 'no'
    extra = ''
    if merged == 'no':
        up = git(d, 'rev-parse', '--abbrev-ref', '@{u}'); un = git(d, 'rev-list', '--count', '@{u}..HEAD') if up else 'no-upstream'
        rem = 'yes' if git(d, 'branch', '-r', '--list', f'*/{br}') else 'no'
        extra = f"{un}\t{rem}\t{git(d,'log','-1','--format=%s')[:70]}"
    print(f"{short(d)}\t{n}\texists\t{br}\t{dirty}\t{default}\t{ahead}\t{merged}\t{git(d,'log','-1','--format=%cs')}\t{extra}")
