#!/usr/bin/env python3
"""Print the last N assistant text messages (capped) and the last user message of one transcript. Usage: transcript_lastmsgs.py FILE [N] [CAP]"""
import sys, json
f = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 1; cap = int(sys.argv[3]) if len(sys.argv) > 3 else 3500
A = []; U = []
for ln in open(f, errors='replace'):
    try: o = json.loads(ln)
    except Exception: continue
    if o.get('isSidechain'): continue
    c = o.get('message', {}).get('content')
    if o.get('type') == 'assistant' and isinstance(c, list):
        t = ' '.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text').strip()
        if t: A.append((o.get('timestamp', '')[:16], t))
    elif o.get('type') == 'user':
        t = c if isinstance(c, str) else ' '.join(b.get('text', '') for b in (c or []) if isinstance(b, dict) and b.get('type') == 'text')
        if t.strip() and not t.startswith('<'): U.append((o.get('timestamp', '')[:16], t.strip()))
for ts, t in A[-n:]: print('ASSISTANT', ts, '\n' + t[:cap], '\n')
print('LAST USER:', U[-1][0], U[-1][1][:300] if U else '')
