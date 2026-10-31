#!/usr/bin/env python3
"""Summarise the kilo-mcp task store (<tasks-dir>/*.json) since a date (read-only).
Prints counts by status; every non-completed task with working dir, isolated branch, branch exists / merged into HEAD, pid alive (for 'running');
then failed/cancelled tasks with no later completed task in the same working directory (likely never redone).
Also reports whether the queue lock file points to a live pid (--lock).
Usage: kilomcp_tasks.py [--tasks-dir DIR] [--lock FILE] [--since YYYY-MM-DD] [--exclude S]..."""
import json, glob, os, collections, datetime, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
ap = add_common(argparse.ArgumentParser(description=__doc__))
ap.add_argument('--tasks-dir', default=os.path.expanduser('~/.local/share/kilo-mcp/tasks')); ap.add_argument('--lock', default=os.path.expanduser('~/.local/share/kilo-mcp/queue-runner.lock'))
a = ap.parse_args(); since = since_ts(a.since)
def alive(pid):
    try: os.kill(int(pid), 0); return True
    except Exception: return False
rows = []
for f in glob.glob(a.tasks_dir + '/*.json'):
    if os.stat(f).st_mtime < since: continue
    try: j = json.load(open(f))
    except Exception: continue
    j['_id'] = os.path.basename(f)[:-5]; j['_mt'] = os.stat(f).st_mtime; rows.append(j)
rows = [r for r in rows if not excluded(str(r.get('working_directory')), a.exclude)]
print('COUNTS', dict(collections.Counter(r['status'] for r in rows)))
if os.path.exists(a.lock):
    txt = open(a.lock, errors='replace').read().strip()
    pid = ''.join(ch for ch in txt.split()[0] if ch.isdigit()) if txt else ''
    print('QUEUE_LOCK', a.lock, 'content=', txt[:60], 'pid_alive=', alive(pid) if pid else 'unknown')
print('STATUS\tid\tstarted\tworkdir\tbranch\tbranch_exists\tmerged_into_HEAD\tpid_alive\tresult_head')
for r in sorted(rows, key=lambda r: r['_mt']):
    if r['status'] == 'completed': continue
    wd = r.get('working_directory') or ''; br = r.get('isolated_branch') or ''; ex = mg = ''
    if br and os.path.isdir(wd):
        ex = 'yes' if git_ok(wd, 'rev-parse', '--verify', '-q', br) else 'no'
        if ex == 'yes': mg = 'yes' if git_ok(wd, 'merge-base', '--is-ancestor', br, 'HEAD') else 'NO'
    res = r.get('result'); res = (json.dumps(res) if not isinstance(res, str) else res or '')[:70].replace('\n', ' ')
    print('\t'.join([r['status'], r['_id'], str(r.get('started'))[:16], short(wd), br, ex, mg, str(alive(r.get('pid'))) if r['status'] == 'running' else '', res]))
print('\nNOT_RETRIED (failed/cancelled, no later completed task in same dir):')
by = collections.defaultdict(list)
for r in rows: by[r.get('working_directory')].append(r)
for wd, L in sorted(by.items(), key=lambda kv: str(kv[0])):
    L.sort(key=lambda r: r['_mt'])
    for i, r in enumerate(L):
        if r['status'] in ('failed', 'cancelled') and not any(x['status'] == 'completed' and x['_mt'] > r['_mt'] for x in L[i+1:]):
            res = r.get('result'); res = (json.dumps(res) if not isinstance(res, str) else res or '')[:90].replace('\n', ' ')
            print('\t'.join([r['status'], r['_id'], datetime.datetime.fromtimestamp(r['_mt']).strftime('%m-%d %H:%M'), short(str(wd)), res]))
