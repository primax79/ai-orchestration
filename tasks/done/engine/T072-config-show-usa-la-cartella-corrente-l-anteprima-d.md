# T072 config show usa la cartella corrente; l'anteprima di reassign mostra il percorso reale

- id: T072
- title: config show usa la cartella corrente; l'anteprima di reassign mostra il percorso reale
- category: engine
- priority: P3
- priority-reason: Comportamento diverso dagli altri comandi; l'anteprima fa credere che il file stia nel repo
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-144358-config-show-ignores-the-current-director/note.md
- paths: ai-orch config show; ai-orch orchestrator reassign --dry-run
- handoff: Read tasks/engine/T072-config-show-usa-la-cartella-corrente-l-anteprima-d.md, do the open steps, run the Verification, update the task and the registry.
- verifier: d4science_kb
- verify-by: d4science_kb
- short: config show nella cartella

## Goal

1. In ~/works/d4science_kb, `ai-orch config show` prints 'Project config: None (exists=False)', while `ai-orch config show --workspace ~/works/d4science_kb` finds ~/.config/ai-orchestration/projects/d4science_kb/orchestration.toml (written by reassign). Other groups (orchestrator, sessions) default --workspace to the current directory; config show does not. Expected: same default.
2. `orchestrator reassign --dry-run` shows the diff as 'a/orchestration.toml' / 'b/orchestration.toml', which reads as a file in the repo root; the file goes to ~/.config/ai-orchestration/projects/<name>/. Expected: the diff header names the real path.

## Steps

- [x] config show: --workspace predefinito = cartella corrente, come orchestrator e sessions
- [x] Diff dell'anteprima di reassign con il percorso reale del file

## Verification

- Test eseguiti con successo in `test_orchestration_config.py` e `test_orchestration_orchestrator.py`:
  - `test_config_show_defaults_to_cwd`: `ai-orch config show` e `cmd_show` senza `--workspace` risolvono la cartella corrente come default, trovando la configurazione di progetto in `~/.config/ai-orchestration/projects/<nome>/orchestration.toml` (sia in formato JSON che testo formattato); `--workspace` esplicito continua a funzionare sovrascrivendo la cartella corrente.
  - `test_format_diff_path`: formattazione corretta degli header diff per percorsi relativi alla home (`a/~/.config/...`), percorsi assoluti fuori home (`a/<path>`) e percorsi locali al workspace (`a/.ai-orchestration.local.toml`), evitando sempre intestazioni bare come `a/orchestration.toml`.
  - `test_reassign_dry_run_shows_plan`, `test_reassign_cli`, `test_reassign_dry_run_diff_header_home_relative`, `test_reassign_dry_run_diff_header_absolute_path_outside_home`: verifica che l'anteprima diff di reassign mostri sempre il percorso target reale e mai `--- a/orchestration.toml`.
- Suite completa passata: `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider scripts/ plugins/shared/skills/orchestration-setup/scripts/` (364 passati su 364).

## Log (newest first)

- 2026-10-27, d4science-kb-3d: state `verified` -> `done` — validated by d4science_kb (verify-by)
- 2026-10-27, d4science_kb: state `delivered` -> `verified` — re-ran the N069 scenario on 2026-10-27 with architect-side 0.8.3
- 2026-10-27, kilo: state `open` -> `delivered` — config show adotta la cartella corrente come workspace di default e il diff di reassign mostra il percorso reale del file
