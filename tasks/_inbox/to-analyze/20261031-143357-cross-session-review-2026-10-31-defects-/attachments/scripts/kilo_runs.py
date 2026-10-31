#!/usr/bin/env python3
"""Kilo root-session inventory since a date (read-only on the Kilo SQLite DB). Output TSV on stdout.
Per root session: directory, title, agent, model, cost, created/updated, #messages, last message role + finish reason, last part type/status,
tool errors, open todos, child sessions, git branch + dirty count of the directory.
'finish' not starting with 'stop' means the run ended mid-run or errored (often a cancel after commit: a hint, not proof).
Usage: kilo_runs.py [--db PATH] [--since YYYY-MM-DD] [--exclude SUBSTR]..."""
import sqlite3, sys, os, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
ap = add_common(argparse.ArgumentParser(description=__doc__)); ap.add_argument('--db', default=os.path.expanduser('~/.local/share/kilo/kilo.db'))
a = ap.parse_args(); since = int(since_ts(a.since) * 1000)
c = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True)
ts = lambda ms: datetime.datetime.fromtimestamp(ms / 1000).strftime('%m-%d %H:%M')
rows = c.execute("select id,parent_id,directory,title,agent,model,cost,time_created,time_updated from session where time_created>=? order by time_created", (since,)).fetchall()
print('\t'.join(['id','dir','exists','title','agent','model','cost','created','updated','nmsg','last_role','last_part','tool_err','todo_open','children','git']))
for sid, par, d, title, agent, model, cost, tc, tu in rows:
    if par or excluded(d, a.exclude): continue
    nm = c.execute("select count(*) from message where session_id=?", (sid,)).fetchone()[0]
    lm = c.execute("select data from message where session_id=? order by time_created desc limit 1", (sid,)).fetchone()
    role = fin = ''
    if lm: j = json.loads(lm[0]); role = j.get('role', ''); fin = str(j.get('finish', '')) + (' ERR' if j.get('error') else '')
    lp = c.execute("select data from part where session_id=? order by time_created desc limit 1", (sid,)).fetchone(); lps = ''
    if lp: j = json.loads(lp[0]); lps = j.get('type', '') + ':' + str((j.get('state') or {}).get('status', j.get('reason', '')))
    te = c.execute("select count(*) from part where session_id=? and json_extract(data,'$.state.status')='error'", (sid,)).fetchone()[0]
    todo = c.execute("select count(*) from todo where session_id=? and status not in ('completed','cancelled')", (sid,)).fetchone()[0]
    ch = c.execute("select count(*) from session where parent_id=?", (sid,)).fetchone()[0]
    g = ''
    if os.path.isdir(d): g = f"{git(d,'rev-parse','--abbrev-ref','HEAD')} dirty={len(git(d,'status','--porcelain').splitlines())}"
    print('\t'.join(map(str, [sid, d, os.path.isdir(d), (title or '')[:70].replace('\t', ' '), agent, (model or '')[:30], round(cost or 0, 2), ts(tc), ts(tu), nm, role, fin + '|' + lps, te, todo, ch, g])))
