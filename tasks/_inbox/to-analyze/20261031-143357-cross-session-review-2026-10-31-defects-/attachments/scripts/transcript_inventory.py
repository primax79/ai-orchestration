#!/usr/bin/env python3
"""List Claude Code transcripts modified since a date: project dir, session id (8 chars), mtime, size, user turns, first user message (110 chars).
Usage: transcript_inventory.py [--root DIR] [--include SUBSTR]... [--exclude SUBSTR]... [--since YYYY-MM-DD]"""
import sys, os, json, glob, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
ap = add_common(argparse.ArgumentParser(description=__doc__), projects=True); a = ap.parse_args(); since = since_ts(a.since)
def text_of(m):
    c = m.get('message', {}).get('content')
    if isinstance(c, str): return c
    if isinstance(c, list): return ' '.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')
    return ''
for d, full in project_dirs(a.root, a.include, a.exclude):
    for f in sorted(glob.glob(os.path.join(full, '*.jsonl'))):
        st = os.stat(f)
        if st.st_mtime < since: continue
        first = ''; n = 0
        for line in open(f, errors='replace'):
            try: o = json.loads(line)
            except Exception: continue
            if o.get('type') == 'user' and not o.get('isSidechain'):
                t = text_of(o).strip()
                if t and not t.startswith('<') and not first: first = t[:110].replace('\n', ' ')
                n += 1
        print(f"{d[-45:]}\t{os.path.basename(f)[:8]}\t{datetime.datetime.fromtimestamp(st.st_mtime):%m-%d %H:%M}\t{st.st_size//1024}K\tu={n}\t{first}")
