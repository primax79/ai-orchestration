# N039 Cross-workspace executor and depends-on links with live state

- id: N039
- title: Cross-workspace executor and depends-on links with live state
- kind: feature
- status: processed
- created: 2026-10-21T08:16:56.022022+00:00
- author: d4science-evolution-assurance
- about: 16.4 qualified refs; 16.9; broker
- produced: T043
- processed-by: ai-coding-tools

Tasks executed in another workspace (e.g. done by ai-coding-tools, gcube-atlas, d4science-python-library) sit 'in progress' with the remote id written in the steps by hand. Wanted: 'executor: <workspace>:T030' and cross-workspace depends-on resolved through the registry and shown with the remote task's live state (like coordinates inside a workspace). Source: N035 consultation; worth more to them than custom states.
