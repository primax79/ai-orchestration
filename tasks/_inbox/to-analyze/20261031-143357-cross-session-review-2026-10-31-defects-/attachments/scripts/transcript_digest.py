#!/usr/bin/env python3
"""Digest Claude Code transcripts into compact text for pending-work review (read-only). One output file per project dir.
Per session: first/last timestamp, user messages (first/last 6), last assistant messages, outgoing SendMessage and incoming
cross-session messages, Agent launches with whether a result was seen, and open-work phrases from the last assistant messages.
Tool results are never printed raw; token-like strings are redacted. Digests quote transcripts: keep them private, do not commit.
Usage: transcript_digest.py OUTDIR [--root DIR] [--include SUBSTR]... [--exclude SUBSTR]... [--since YYYY-MM-DD] [--phrases REGEX]"""
import json, os, re, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
ap = add_common(argparse.ArgumentParser(description=__doc__), projects=True)
ap.add_argument('outdir')
ap.add_argument('--phrases', default=r"(\bpending\b|\bTODO\b|next step|\bwaiting\b|not done|still open|follow-up|left open|owner decision|want me to|shall I|should I|blocked)",
                help='regex of open-work phrases (add your own language)')
a = ap.parse_args(); since = since_ts(a.since); PH = re.compile(a.phrases, re.I)
SECRET = re.compile(r"(eyJ[A-Za-z0-9_-]{20,}|[A-Fa-f0-9]{32,}|password\s*[:=]\s*\S+|token\s*[:=]\s*\S{16,})")
def texts(c):
    if isinstance(c, str): return [c]
    return [b.get('text', '') for b in (c or []) if isinstance(b, dict) and b.get('type') == 'text']
def clip(s, n):
    s = SECRET.sub('[REDACTED]', re.sub(r'\s+', ' ', s)).strip(); return s if len(s) <= n else s[:n] + '...'
def digest(path):
    msgs = []; agents = {}; sent = []; recv = []; users = []; phr = []; first = last = title = None
    for line in open(path, errors='replace'):
        try: d = json.loads(line)
        except Exception: continue
        t = d.get('type'); ts = d.get('timestamp')
        if ts: first = first or ts; last = ts
        if t == 'ai-title': title = d.get('aiTitle') or d.get('title') or title
        m = d.get('message')
        if t not in ('user', 'assistant') or not isinstance(m, dict) or d.get('isSidechain'): continue
        c = m.get('content')
        if t == 'user':
            for x in texts(c):
                if '<cross-session-message' in x: recv.append((ts, clip(x, 500)))
                elif 'task-notification' in x[:80]: users.append((ts, 'NOTIF ' + clip(x, 200)))
                elif x.strip() and not x.startswith(('<system-reminder', '<command', 'Caveat')): users.append((ts, clip(x, 400)))
            for b in (c if isinstance(c, list) else []):
                if isinstance(b, dict) and b.get('type') == 'tool_result' and b.get('tool_use_id') in agents:
                    agents[b['tool_use_id']]['res'] = clip(json.dumps(b.get('content'))[:400], 250)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                if b.get('type') == 'tool_use':
                    n = b.get('name', ''); i = b.get('input', {})
                    if n.endswith('SendMessage'): sent.append((ts, i.get('to'), clip(str(i.get('message')), 450)))
                    if n in ('Agent', 'Task'): agents[b['id']] = {'ts': ts, 'desc': i.get('description'), 'bg': i.get('run_in_background'), 'res': None}
                if b.get('type') == 'text': msgs.append((ts, b['text']))
    for ts, tx in msgs[-25:]:
        for s in re.split(r'(?<=[.!?\n])\s+', tx):
            if PH.search(s): phr.append((ts, clip(s, 220)))
    return dict(first=first, last=last, title=title, users=users, last_asst=msgs[-3:], sent=sent, recv=recv, agents=agents, phr=phr[-12:], nmsg=len(msgs))
os.makedirs(a.outdir, exist_ok=True)
for dname, full in project_dirs(a.root, a.include, a.exclude):
    fs = [f for f in glob.glob(full + '/*.jsonl') if os.path.getmtime(f) >= since]
    if not fs: continue
    out = []
    for f in sorted(fs, key=os.path.getmtime):
        g = digest(f)
        out.append(f"\n=== SESSION {os.path.basename(f)[:8]} {g['first']} -> {g['last']} size={os.path.getsize(f)//1024}K asst_msgs={g['nmsg']} title={g['title']}")
        out.append(f"-- USER ({len(g['users'])}), first 6 and last 6")
        for ts, x in g['users'][:6] + (g['users'][-6:] if len(g['users']) > 12 else g['users'][6:]): out.append(f"  [{ts}] {x}")
        out.append("-- LAST ASSISTANT"); out += [f"  [{ts}] {clip(x, 900)}" for ts, x in g['last_asst']]
        out.append(f"-- SENT {len(g['sent'])}"); out += [f"  [{ts}] to={to}: {x}" for ts, to, x in g['sent']]
        out.append(f"-- RECEIVED {len(g['recv'])}"); out += [f"  [{ts}] {x}" for ts, x in g['recv']]
        out.append(f"-- AGENTS {len(g['agents'])}")
        out += [f"  [{v['ts']}] {v['desc']} bg={v['bg']} result={'YES' if v['res'] else 'NO'} {v['res'] or ''}"[:380] for v in g['agents'].values()]
        out.append("-- OPEN-WORK PHRASES (last 12)"); out += [f"  [{ts}] {x}" for ts, x in g['phr']]
    open(os.path.join(a.outdir, dname.strip('-')[-60:] + '.txt'), 'w').write('\n'.join(out))
    print(dname, len(fs))
