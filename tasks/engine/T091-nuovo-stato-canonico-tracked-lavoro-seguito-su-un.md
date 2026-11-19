# T091 Nuovo stato canonico tracked: lavoro seguito su un tracker esterno

- id: T091
- title: Nuovo stato canonico tracked: lavoro seguito su un tracker esterno
- category: engine
- priority: P0
- priority-reason: Urgente (owner, 2026-11-19): il passaggio di consegne di porting_liferay deve distinguere il lavoro nostro da quello seguito su Redmine
- next-up: yes
- state: in progress
- executor: claude
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261119-170944-urgent-p0-new-task-state-tracked-work-fo/note.md, _inbox/analyzed/20261119-171148-urgent-p0-part-of-n094-header-field-trac/note.md
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/architect-side/skills/task-pipeline/SKILL.md, plugins/architect-side/skills/task-pipeline/references/template.md, plugins/architect-side/skills/orchestration-workflow/SKILL.template.md, scripts/orchestration_runs.py, tasks/specs/task-and-state-model.md
- handoff: Read tasks/engine/T091-nuovo-stato-canonico-tracked-lavoro-seguito-su-un.md, do the open steps, run the Verification, update the task and the registry.
- kind: feature
- short: Stato tracked

## Goal

Aggiungere lo stato canonico non terminale `tracked` (forma parametrica `tracked (<ref>, <owner>)`) per il lavoro che vive su un tracker esterno ed è di altri: il task locale resta solo come collegamento e si chiude quando si chiude il ticket. Distinto da `waiting` (lavoro nostro in attesa di qualcosa).

## Steps

- [x] Stato tracked in CANONICAL_STATES, normalize_state con forma parametrica (parse_tracked_state separa ref e owner)
- [x] Transizioni open|in progress|waiting|blocked|paused -> tracked; tracked -> done|done with a caveat|dropped|open|in progress; tasks close va diretto allo stato terminale
- [x] Derivazione dei contenitori e stadio dei use case come waiting; validate lo accetta; mai nella coda ready; nessuna modalità di run
- [x] sync-index: riga `Tracked on an external tracker: N of M active tasks` in testa a Tasks by category (anche nel merge driver), solo se ci sono task tracked
- [x] SKILL.md, template, blocco gestito di AGENTS.md, tabella stati di orchestration-workflow, spec del modello di stato; test
- [x] N096: campo header opzionale `tracker` (lista di URL completi, anche come link Markdown) prima di `short`; validate: errore su un elemento non URL, warning su un task tracked senza tracker; tasks show (JSON e testo) elenca i link
- [ ] Seguito: `tasks tracker-sync --dry-run` (adapter, Redmine REST per primo, sola lettura): propone la chiusura solo quando tutti i ticket sono chiusi, `dropped` se tutti Rejected
- [ ] Seguito (altri repo): ai-orchestration-ui e vscode-ai-orchestration conoscono `tracked` e rendono `tracker` come link cliccabili; colonna o conteggio dei link nel registro
- [ ] Seguito: rilascio del motore e propagazione della skill (porting_liferay converte i suoi `waiting (Redmine #N, ...)`): decisione del proprietario
- [ ] Seguito: kilo-mcp rigenera il binding di orchestration-workflow (riga `tracked` nella tabella stati)

## Verification

- Suite di test del progetto verde; nuovi test per stato, transizioni, derivazione e registro
- tasks validate accetta tracked (Redmine #1, NetFarm)

## Log (newest first)

- 2026-11-19, claude: implementazione su main (commit a2ea4ab stato tracked; commit successivo campo tracker, N096). Suite `uvx --python 3.12 pytest ./scripts ./plugins`: 645 passed, 2 failed preesistenti (test_orchestration_env duplicate-name, T088, già falliti su HEAD prima della modifica). Con Python 3.10 la suite fallisce in massa per `tomllib` mancante: usare 3.11+.
