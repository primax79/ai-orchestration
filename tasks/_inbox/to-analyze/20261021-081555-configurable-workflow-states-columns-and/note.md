# N035 Configurable workflow: states, columns and mapping in the config

- id: N035
- title: Configurable workflow: states, columns and mapping in the config
- kind: idea
- status: draft
- created: 2026-10-21T08:15:55.752166+00:00
- author: owner
- about: tasks_engine.py CANONICAL_STATES/ALLOWED_TRANSITIONS; UI Kanban; broker
- produced: -
- processed-by: -
- short: configurable workflow

Owner idea (2026-10-21): states and flow are hard-coded in ai-orchestration; make them configurable, keeping today's states as the default. The config would define the states, the columns that make up the flow, and the mapping. Proposal (ai-coding-tools): fixed semantic categories in code (todo, active, on-hold, review, accepted, closed, rejected, cancelled) that all engine logic uses (derived parent state, ready queue, independent-verifier guard, archive, counts, conditions); configurable states each mapped to one category; transitions configurable or derived from categories; Kanban columns as ordered groups of states; guards bound to categories; precedence global > workspace > project; aggregate views by category; rename via a previewed migration. Status: being evaluated with the sessions that use the tooling; no decision yet.
