# T091 Nuovo stato canonico tracked: lavoro seguito su un tracker esterno

- id: T091
- title: Nuovo stato canonico tracked: lavoro seguito su un tracker esterno
- category: engine
- priority: P0
- priority-reason: Urgente (owner, 2026-11-19): il passaggio di consegne di porting_liferay deve distinguere il lavoro nostro da quello seguito su Redmine
- next-up: yes
- state: open
- executor: claude
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261119-170944-urgent-p0-new-task-state-tracked-work-fo/note.md
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Read tasks/engine/T091-nuovo-stato-canonico-tracked-lavoro-seguito-su-un.md, do the open steps, run the Verification, update the task and the registry.
- kind: feature
- short: Stato tracked

## Goal

Aggiungere lo stato canonico non terminale `tracked` (forma parametrica `tracked (<ref>, <owner>)`) per il lavoro che vive su un tracker esterno ed è di altri: il task locale resta solo come collegamento e si chiude quando si chiude il ticket. Distinto da `waiting` (lavoro nostro in attesa di qualcosa).

## Steps

- [ ] Stato tracked in CANONICAL_STATES, normalize_state con forma parametrica
- [ ] Transizioni open|in progress|waiting|blocked|paused -> tracked; tracked -> done|done with a caveat|dropped|open|in progress
- [ ] Derivazione dei contenitori come waiting; validate lo accetta
- [ ] sync-index: conteggio separato nel registro (Seguiti su tracker)
- [ ] SKILL.md, template AGENTS.md e copie duplicate in plugins/ aggiornati; test
- [ ] Seguito (non richiesto ora): convenzione per il riferimento al ticket e tasks tracker-sync --dry-run (Redmine REST, sola lettura)

## Verification

- Suite di test del progetto verde; nuovi test per stato, transizioni, derivazione e registro
- tasks validate accetta tracked (Redmine #1, NetFarm)
