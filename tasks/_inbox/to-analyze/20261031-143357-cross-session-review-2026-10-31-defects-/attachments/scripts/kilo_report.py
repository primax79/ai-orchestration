#!/usr/bin/env python3
"""Join kilo_runs.py TSV + kilo_session_refs.py TSV + worktree_state.py TSV into one markdown table of Kilo runs that did NOT end with finish=stop.
Usage: kilo_report.py KILO_RUNS.tsv REFS.tsv WORKTREES.tsv [--db PATH] [--exclude S]..."""
import csv, sys, sqlite3, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
ap = argparse.ArgumentParser(description=__doc__)
for n in ('runs', 'refs', 'wt'): ap.add_argument(n)
ap.add_argument('--db', default=os.path.expanduser('~/.local/share/kilo/kilo.db')); ap.add_argument('--exclude', action='append', default=[])
a = ap.parse_args()
runs = [x for x in list(csv.reader(open(a.runs), delimiter='\t'))[1:] if not excluded(x[1], a.exclude)]
ids = {l.split('\t')[0] for l in open(a.refs)}
wt = {x[0]: x for x in (l.rstrip('\n').split('\t') for l in open(a.wt))}
c = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True)
def lasttext(sid):
    r = c.execute("select data from part where session_id=? and json_extract(data,'$.type')='text' order by time_created desc limit 1", (sid,)).fetchone()
    return json.loads(r[0]).get('text', '')[-220:].replace('\n', ' ').replace('|', '/') if r else ''
print('| session | directory | title | created | end state | referenced in a transcript | worktree | last text |\n|---|---|---|---|---|---|---|---|')
for x in runs:
    sid, d, ex, title, agent, model, cost, cr, up, nm, role, fin = x[:12]
    if fin.startswith('stop'): continue
    state = 'errored (' + fin + ')' if 'ERR' in fin else ('ended mid-run (' + fin.split('|')[1].strip(':') + ')' if fin.startswith('|') else fin)
    w = wt.get(short(d)); ws = 'gone' if w and len(w) > 2 and w[2] == 'GONE' else (f"{w[3]} dirty={w[4]} ahead={w[6]} merged={w[7]}" if w and len(w) > 7 else 'n/a')
    print(f"| ..{sid[-8:]} | {short(d)[-70:]} | {title[:50]} | {cr} | {state} | {'yes' if sid in ids else 'NO'} | {ws} | {lasttext(sid)[:160]} |")
