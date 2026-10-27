# T072 config show usa la cartella corrente; l'anteprima di reassign mostra il percorso reale

- id: T072
- title: config show usa la cartella corrente; l'anteprima di reassign mostra il percorso reale
- category: engine
- priority: P3
- priority-reason: Comportamento diverso dagli altri comandi; l'anteprima fa credere che il file stia nel repo
- next-up: no
- state: in progress
- executor: kilo
- depends-on: -
- decider: -
- sources: _inbox/analyzed/20261027-144358-config-show-ignores-the-current-director/note.md
- paths: ai-orch config show; ai-orch orchestrator reassign --dry-run
- handoff: Read tasks/engine/T072-config-show-usa-la-cartella-corrente-l-anteprima-d.md, do the open steps, run the Verification, update the task and the registry.
- verify-by: d4science_kb
- short: config show nella cartella

## Goal

1. In ~/works/d4science_kb, `ai-orch config show` prints 'Project config: None (exists=False)', while `ai-orch config show --workspace ~/works/d4science_kb` finds ~/.config/ai-orchestration/projects/d4science_kb/orchestration.toml (written by reassign). Other groups (orchestrator, sessions) default --workspace to the current directory; config show does not. Expected: same default.
2. `orchestrator reassign --dry-run` shows the diff as 'a/orchestration.toml' / 'b/orchestration.toml', which reads as a file in the repo root; the file goes to ~/.config/ai-orchestration/projects/<name>/. Expected: the diff header names the real path.

## Steps

- [ ] config show: --workspace predefinito = cartella corrente, come orchestrator e sessions
- [ ] Diff dell'anteprima di reassign con il percorso reale del file

## Verification

- Test: config show dalla cartella del workspace trova la config di progetto; header del diff con il percorso reale
