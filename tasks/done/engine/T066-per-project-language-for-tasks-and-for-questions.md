# T066 Lingua per progetto per i task e per le domande

- id: T066
- title: Lingua per progetto per i task e per le domande
- category: engine
- priority: P2
- priority-reason: Richiesta dell'owner 2026-10-27; i progetti scrivono i task in una lingua e pongono le domande all'owner in un'altra (dave_agent: task in italiano)
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: owner 2026-10-27: 'prevediamo una configurazione, per progetto, della lingua da usare per task e domande. potrebbero non coincidere'; builds on T065 (use-case Italian headings, --lang)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py,plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Leggi tasks/engine/T066-per-project-language-for-tasks-and-for-questions.md, esegui i passi aperti, lancia la Verification, aggiorna il task e il registro.
- verifier: ai-coding-tools-c1
- short: Lingue per progetto

## Cambio di ambito 2026-10-27 (owner)

"le keyword possono restare in inglese, anzi, formalizziamole in inglese; poi eventualmente si fa interfaccia localizzabile".
Le intestazioni di sezione (Goal, Steps, Verification, Log; Context/Options/Recommendation/Answer per le domande; sezioni dei casi d'uso) e
i nomi dei campi dell'header costituiscono un vocabolario formale INGLESE del formato, mai tradotto. Le impostazioni della lingua governano solo
il CONTENUTO (la prosa di titoli, obiettivi, passi, domande) scritto dalle sessioni. La visualizzazione localizzata è un tema futuro per la UI.
Conseguenza per T065: i casi d'uso tornano a essere generati con intestazioni in inglese; gli alias in italiano delle intestazioni restano leggibili
per i file già scritti in quel modo (compatibilità), e validate emette un avviso per normalizzarli.

## Goal

Un progetto dichiara, nel proprio albero tasks versionato, la lingua dei suoi task e, separatamente, quella delle domande rivolte all'owner (possono differire), ad es. task in inglese e domande in italiano. La dichiarazione avviene nello stesso punto dei campi di estensione (blocco toml delimitato in tasks/AGENTS.md, come in T050): [tasks] language = "en", [questions] language = "it"; i casi d'uso seguono la lingua dei task a meno che non sia impostato [use_cases] language; valore predefinito en. Un unico resolver sostituisce l'espressione regolare in _detect_use_case_language (continuando a leggere le vecchie chiavi per compatibilità, con un avviso di deprecazione). Effetti: il blocco gestito di AGENTS.md dichiara entrambe le lingue affinché ogni sessione scriva di conseguenza; tasks new, questions ask e use-cases create usano template/intestazioni localizzati dove il motore li prevede (it, en); validate accetta gli alias delle intestazioni localizzate; tasks show/config riportano le lingue effettive. Non è una configurazione locale alla macchina: le lingue sono una convenzione del progetto, versionata insieme a tasks/.

## Steps

- [x] Un unico resolver `resolve_project_languages` per le lingue del progetto (`[tasks] language`, `[questions] language`, `[use_cases] language`, con i casi d'uso che ereditano per impostazione predefinita la lingua dei task e valore predefinito generale `en`) in `tasks/AGENTS.md` dal blocco `toml` delimitato; validazione BCP-47 con avviso su valori vuoti/malformati; compatibilità con le chiavi legacy di T065 (`use_case_language`/`language` in `orchestration.toml` / `.ai-orchestration.local.toml`) con avviso di deprecazione in `validate`; sottocomandi `tasks config` / `show-config` e indicazione della lingua in `tasks show --json`.
- [x] Il blocco gestito di `AGENTS.md` (`CANONICAL_TASKS_AGENTS_MD` / `build_managed_tasks_agents_block` / `render_upgraded_agents_md`) dichiara sempre che le intestazioni di sezione e i nomi dei campi dell'header sono parole chiave fisse in inglese e, quando le lingue sono dichiarate, aggiunge la riga con le lingue effettive dei contenuti (`Content language: tasks ..., questions ..., use cases ...`); documentato in `task-pipeline/SKILL.md`.
- [x] I template (`tasks new`, `questions ask`, `use-cases create`) emettono sempre intestazioni fisse in inglese; `use-cases create --lang it` (e la lingua `it` del progetto per i casi d'uso) mantiene la prosa predefinita localizzata in italiano emettendo però intestazioni in inglese; i file dei casi d'uso esistenti con intestazioni in italiano restano leggibili e `validate` avvisa con `non-standard heading '<it>' (use '<en>')`.
- [x] Aggiunti unit test in `test_tasks_engine.py` (`test_t066_project_languages_and_english_headings_keywords` e aggiornato `test_t057_t061_t062_t063_t052_and_n064`) a copertura delle dichiarazioni `it`/`it`, degli output predefiniti identici byte per byte, di `use-cases create --lang it` con intestazioni in inglese + prosa in italiano + avvisi di normalizzazione sulle intestazioni legacy in italiano, dell'avviso di deprecazione sulle chiavi legacy di T065 e di `config`/`show-config`.

## Verification

- [x] `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` -> `233 passed`.
- [x] Controllo su copia temporanea di `/Users/Alfredo/works/dave_agent/tasks`: prima delle modifiche `0 errors, 21 warnings`; dopo aver dichiarato `[tasks] language = "it"`, `[questions] language = "en"` in `AGENTS.md` nel blocco `toml` delimitato, `config` risolve `tasks=it, questions=en, use_cases=it` e `validate` riporta `0 errors, 21 warnings` (0 nuovi avvisi sui file con intestazioni in inglese); su un caso d'uso con intestazioni in italiano di T065 (`Descrizione`, `Precondizioni`, `Scenario`, `Comando di verifica`, `Criteri di accettazione`, `Registro delle verifiche`), `validate` emette `0 errors` e solo i 6 avvisi di normalizzazione (`non-standard heading '...' (use '...')`).

## Log (newest first)

- 2026-10-27, ai-coding-tools-c1: state `verified` -> `done`
- 2026-10-27, ai-coding-tools-c1: state `delivered` -> `verified`
- 2026-10-27, kilo: state `open` -> `delivered` — Implementati il resolver per progetto della lingua dei contenuti, le regole delle parole chiave fisse in inglese in AGENTS.md/SKILL.md, le intestazioni in inglese su use-cases create con avvisi di normalizzazione sulle intestazioni legacy in italiano, e `tasks config`/`show-config`.
