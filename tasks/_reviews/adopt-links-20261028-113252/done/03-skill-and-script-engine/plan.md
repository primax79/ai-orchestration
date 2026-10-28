# 03 - Skill di configurazione e gestione dei task + script Python

- **Short:** Script config e task

> **Derived from specs:** [`../specs/orchestration-config-and-agents-md.md`](../../specs/orchestration-config-and-agents-md.md), [`../specs/task-and-state-model.md`](../../specs/task-and-state-model.md)

## Tasks

### 03.1 - Completare `orchestration_config.py`, gli unit test e l'aggiornamento della skill `interactive-role-setup`
- **Profile:** `bulk-execution`
- **Status:** `done` (2026-10-15) · **Short:** Completamento motore config
- **Focus files:** `plugins/shared/skills/interactive-role-setup/scripts/orchestration_config.py`, `plugins/shared/skills/interactive-role-setup/scripts/test_orchestration_config.py`, `plugins/shared/skills/interactive-role-setup/SKILL.md`
- **Steps:**
  1. Scrivere unit test `pytest` completi in `plugins/shared/skills/interactive-role-setup/scripts/test_orchestration_config.py` per verificare:
     - fusione profonda (deep merge) di `orchestration.toml` globale + di progetto;
     - `set-profile` (ambiti globale e di progetto);
     - `validate` (intercettazione di `xhigh` su modelli non supportati, modalità di verifica non valide, tool sconosciuti);
     - `render-agents-md` (`--apply` e `--check`, preservando il contenuto esterno ai marcatori `<!-- BEGIN ai-orchestration --> ... <!-- END ai-orchestration -->` e generando le tabelle nello stile di `ricerca_auto`).
  2. Aggiornare `plugins/shared/skills/interactive-role-setup/SKILL.md` per guidare l'utente nella nuova configurazione multi-tool di `orchestration.toml` globale + di progetto, nell'instradamento della verifica incrociata tra agenti e nel flusso di lavoro `render-agents-md` tramite `scripts/orchestration_config.py`.
- **Verification:**
  - `pytest plugins/shared/skills/interactive-role-setup/scripts/test_orchestration_config.py` passa al 100%.
  - `python3 scripts/generate_skill_indices.py` termina con codice 0.
- **Commit:** Singolo commit limitato a `03.1`.

### 03.2 - Implementare `tasks_engine.py` (parser deterministico dei task, validatore, transizioni di stato e sincronizzazione di `00-INDEX.md`)
- **Profile:** `deep-reasoning`
- **Status:** `done` (2026-10-15) · **Short:** Motore dei task
- **Focus files:** `plugins/architect-side/skills/macroplan-authoring/scripts/tasks_engine.py`, `plugins/architect-side/skills/macroplan-authoring/scripts/test_tasks_engine.py`
- **Steps:**
  1. Implementare `tasks_engine.py` (Python con sola libreria standard, supporto a `--json` su tutti i sottocomandi):
     - `list [--tasks-dir <dir>] [--json]`: analizza tutti i task `T###` e `NN-<slug>` producendo JSON strutturato.
     - `validate [--tasks-dir <dir>] [--json]`: verifica l'unicità degli ID (inclusa `done/`), l'ordine dell'insieme chiuso di intestazioni, la validità di stati/priorità/profili, l'aciclicità del DAG su `depends-on`, i link Markdown relativi e gli invarianti dei gate di verifica.
     - `transition <task_id> <new_state> [--actor <actor>] [--verifier <verifier>] [--reason <text>] [--tasks-dir <dir>]`: applica le guardie della macchina a stati da `tasks/specs/task-and-state-model.md` (ad es. blocca `in progress → done`, impone `verifier != executor` o l'approvazione dell'owner su `delivered → verified`, gestisce `git mv` in `done/` alla chiusura) e accoda una voce di log con timestamp a `PROGRESS.md`.
     - `sync-index [--tasks-dir <dir>] [--apply] [--check]`: rigenera o verifica deterministicamente `tasks/00-INDEX.md` (`Next up`, `Tasks by category`, `Decisions waiting`, `Done`) a partire dalle intestazioni dei task su disco.
  2. Scrivere `test_tasks_engine.py` coprendo il parsing, gli errori di validazione, le transizioni di stato lecite e illecite, la guardia di verifica incrociata tra agenti e `sync-index`.
- **Verification:**
  - `pytest plugins/architect-side/skills/macroplan-authoring/scripts/test_tasks_engine.py` passa al 100%.
  - `python3 plugins/architect-side/skills/macroplan-authoring/scripts/tasks_engine.py validate --tasks-dir tasks` termina con codice 0.
- **Commit:** Singolo commit limitato a `03.2`.
