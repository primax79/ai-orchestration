#!/usr/bin/env python3
import argparse, datetime, os, subprocess, glob

def add_common(ap, projects=False):
    ap.add_argument('--since', default=None, help='ISO date (YYYY-MM-DD); default: 10 days ago')
    ap.add_argument('--exclude', action='append', default=[], help='substring; skip paths containing it (repeatable)')
    if projects:
        ap.add_argument('--root', default=os.path.expanduser('~/.claude/projects'), help='Claude Code projects dir')
        ap.add_argument('--include', action='append', default=[], help='substring of project dir name (repeatable); default: all')
    return ap

def since_ts(s):
    if s: return datetime.datetime.strptime(s, '%Y-%m-%d').timestamp()
    return (datetime.datetime.now() - datetime.timedelta(days=10)).timestamp()

def excluded(path, ex): return any(e.lower() in path.lower() for e in ex)

def short(p):
    h = os.path.expanduser('~')
    return p.replace(h, '~', 1) if p.startswith(h) else p

def git(d, *a, timeout=20):
    try: return subprocess.run(['git', '-C', d, *a], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception: return ''

def git_ok(d, *a, timeout=20):
    try: return subprocess.run(['git', '-C', d, *a], capture_output=True, timeout=timeout).returncode == 0
    except Exception: return False

def default_branch(repo):
    for c in ('main', 'master', 'development', 'develop'):
        if git_ok(repo, 'rev-parse', '--verify', '-q', c): return c
    return ''

def project_dirs(root, include, exclude):
    for d in sorted(os.listdir(root)):
        full = os.path.join(root, d)
        if not os.path.isdir(full) or excluded(d, exclude): continue
        if include and not any(i.lower() in d.lower() for i in include): continue
        yield d, full
