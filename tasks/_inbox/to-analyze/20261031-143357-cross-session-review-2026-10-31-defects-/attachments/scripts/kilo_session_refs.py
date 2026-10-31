#!/usr/bin/env python3
"""Which Kilo session ids (ses_...) are mentioned in Claude transcripts: proxy for 'a Claude coordinator saw/collected it'.
Output TSV: id, n_projects, projects. Usage: kilo_session_refs.py [--root DIR] [--include S]... [--exclude S]... [--since YYYY-MM-DD]"""
import sys, os, re, glob, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
a = add_common(argparse.ArgumentParser(description=__doc__), projects=True).parse_args(); since = since_ts(a.since)
rx = re.compile(rb'ses_[0-9a-f]{12}[A-Za-z0-9]{14}'); seen = collections.defaultdict(set)
for d, full in project_dirs(a.root, a.include, a.exclude):
    for f in glob.glob(full + '/*.jsonl'):
        if os.stat(f).st_mtime < since: continue
        for ln in open(f, 'rb'):
            if b'ses_' in ln:
                for m in rx.findall(ln): seen[m.decode()].add(d[-30:])
for k, v in seen.items(): print(k, len(v), ','.join(sorted(v))[:100], sep='\t')
