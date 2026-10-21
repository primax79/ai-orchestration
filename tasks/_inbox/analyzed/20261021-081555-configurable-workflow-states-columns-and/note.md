# N035 Configurable workflow: states, columns and mapping in the config

- id: N035
- title: Configurable workflow: states, columns and mapping in the config
- kind: idea
- status: processed
- created: 2026-10-21T08:15:55.752166+00:00
- author: owner
- about: tasks_engine.py CANONICAL_STATES/ALLOWED_TRANSITIONS; UI Kanban; broker
- produced: not adopted (consultation 2026-10-21: all four user sessions answered not needed)
- processed-by: ai-coding-tools

Owner idea (2026-10-21): states and flow are hard-coded in ai-orchestration; make them configurable, keeping today's states as the default. The config would define the states, the columns that make up the flow, and the mapping. Proposal (ai-coding-tools): fixed semantic categories in code (todo, active, on-hold, review, accepted, closed, rejected, cancelled) that all engine logic uses (derived parent state, ready queue, independent-verifier guard, archive, counts, conditions); configurable states each mapped to one category; transitions configurable or derived from categories; Kanban columns as ordered groups of states; guards bound to categories; precedence global > workspace > project; aggregate views by category; rename via a previewed migration. Consultation 2026-10-21 (gcube-audit, gcube-atlas, d4science-evolution-assurance, d4science-python-library): all four answered NOT NEEDED (at most nice to have). Today's states fit; nobody misses a state; all want ONE shared flow (comparability across sessions and workspaces, unambiguous cross-session verification); keep the independent-verifier guard as is. If built later, the category design is the right shape. What they want instead: cheap closing (T035), questions 'moved' (T041), a waiting-on qualifier (N036), conflict-free index (T037), workspace next (T040), cross-workspace links (N039). Recommendation: do not build now; reopen when a session needs a different flow.
