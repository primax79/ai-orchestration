# T016 Studio: le segnalazioni persistenti del Doctor sono reali e le gestiamo correttamente?

- id: T016
- title: Studio: le segnalazioni persistenti del Doctor sono reali e le gestiamo correttamente?
- category: env-doctor
- priority: P1
- priority-reason: L'owner vede molte segnalazioni del Doctor che non si risolvono mai; o sono falsi positivi o il percorso di risoluzione è rotto, ed entrambi i casi erodono la fiducia nello strumento
- next-up: no
- state: done with a caveat: validated by the architect, no user yet
- executor: claude
- depends-on: -
- decider: -
- sources: owner request (2026-10-17): "a lot of findings that do not resolve; check whether they are false alarms or whether we must change how we handle them"
- paths: scripts/orchestration_env.py, ../ai-orchestration-ui/frontend/src/components/EnvironmentDoctor.tsx
- handoff: Leggere tasks/env-doctor/T016-doctor-findings-study.md e produrre il report in tasks/env-doctor/notes/.
- verifier: owner
- short: Studio segnalazioni Doctor

## Goal

Per ogni segnalazione riportata dal Doctor su questa macchina, stabilire:

1. se è **vera** (un duplicato, conflitto o disallineamento reale), **falsa** (un errore di classificazione del Doctor), oppure **vera ma non risolvibile dal Doctor** (ad esempio una copia di un plugin che solo l'owner può disabilitare);
2. qual è il percorso di risoluzione e perché oggi non elimina la segnalazione;
3. cosa deve cambiare: le regole di classificazione, la logica di risoluzione, la presentazione nella UI (severità, raggruppamento, "riconosci/ignora"), oppure nulla.

## Steps

1. Eseguire `env status --json` e tutti i piani `--dry-run` (`resolve-conflicts`, `install-skills`, `register-mcp`) sulla home reale, in sola lettura.
2. Inventariare ogni segnalazione per tipo (`foreign`, `modified-or-outdated`, `unmanaged`, duplicate-name, trigger-conflict, configurazione orfana, provenienza e override MCP), con i relativi conteggi.
3. Per un campione di ciascun tipo, ispezionare i file reali (diff del contenuto rispetto al repository sorgente o alla copia del plugin, ricevute, symlink) e classificare la segnalazione come vera, falsa o non risolvibile automaticamente.
4. Tracciare in `orchestration_env.py` il motivo per cui la segnalazione persiste dopo la risoluzione dalla UI.
5. Scrivere il report con le modifiche proposte, ciascuna dimensionata e pronta a diventare un task.

## Verification

- `tasks/env-doctor/notes/T016-report.md` esiste, con evidenze (comandi, output, file:riga) per ogni affermazione.
- La home non è stata modificata: una ricerca con find di file più recenti rispetto a un marker impostato all'inizio non restituisce nulla sotto `~/.claude`, `~/.kilo`, `~/.codex` e `~/.config/kilo`.

## Log (newest first)

- 2026-10-23, owner: state `verified` -> `done with a caveat: validated by the architect, no user yet` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
- 2026-10-23, owner: state `delivered` -> `verified` — Validato dalle suite di test automatizzate e approvato dall'owner per la pulizia
