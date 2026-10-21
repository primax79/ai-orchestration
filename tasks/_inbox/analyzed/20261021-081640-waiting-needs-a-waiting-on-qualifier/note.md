# N036 "waiting" needs a waiting-on qualifier

- id: N036
- title: "waiting" needs a waiting-on qualifier
- kind: feature
- status: processed
- created: 2026-10-21T08:16:40.793328+00:00
- author: gcube_audit
- about: -
- produced: T042
- processed-by: ai-coding-tools

"waiting" mixes waiting on the owner and waiting on a third party (team, tracker); the index must tell them apart. A waiting-on field (owner|team|external|...) or a label, shown in the index, not a new state. Source: N035 consultation.
