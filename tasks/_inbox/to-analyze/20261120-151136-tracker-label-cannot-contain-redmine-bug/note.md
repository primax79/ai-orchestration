# N098 tracker label cannot contain ] (Redmine [Bug] prefixes rejected)

- id: N098
- title: tracker label cannot contain ] (Redmine [Bug] prefixes rejected)
- kind: bug
- status: ready
- created: 2026-11-20T15:11:36.727269+00:00
- author: porting_liferay
- about: T091
- produced: -
- processed-by: -
- short: tracker label cannot contain

tracker field: Markdown link label cannot contain ']' (TRACKER_MD_LINK_RE = r"^\[([^\]]+)\]\((\S+)\)$").
Redmine subjects in gCube trackers start with a bracketed prefix ("[Bug] ...", "[Feature 6.2 mancante] ..."), so
`[#32664 «[Bug] portal-accept-invite-portlet: ...»](https://support.d4science.org/issues/32664)` fails validate as
"not a full http(s) URL". The comma splitter in parse_tracker_field already tracks bracket depth, so balanced brackets
in the label could be accepted (e.g. match the last "](" before the URL, or a balanced-bracket label pattern).
Workaround in porting_liferay (2026-11-20): "[X] subject" rewritten as "X: subject". Engine 0.8.20.

---
- Author: porting_liferay
- Workspace: /Users/Alfredo/works/gcube/porting_liferay
- ai-orch: 1.1.0 (fee3a35)
- Date: 2026-11-20 15:11:36 UTC
