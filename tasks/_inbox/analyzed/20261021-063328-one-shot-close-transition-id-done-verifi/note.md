# N018 One-shot close: transition <id> done --verifier

- id: N018
- title: One-shot close: transition <id> done --verifier
- kind: feature
- status: processed
- created: 2026-10-21T06:33:28.739921+00:00
- author: d4science-evolution-assurance
- about: -
- produced: T035
- processed-by: ai-coding-tools

open->in progress->delivered->verified->done is four calls; intermediate ones fail on a wrong state. Wanted: 'transition <id> done --verifier X' walking the legal states and running guards once. Part of their top-2 change.
