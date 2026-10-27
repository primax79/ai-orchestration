# T066 Per-project language for tasks and for questions

- id: T066
- title: Per-project language for tasks and for questions
- category: engine
- priority: P2
- priority-reason: Owner request 2026-10-27; projects write tasks in one language and ask the owner in another (dave_agent: Italian tasks)
- next-up: no
- state: delivered
- executor: kilo
- depends-on: -
- decider: -
- sources: owner 2026-10-27: 'prevediamo una configurazione, per progetto, della lingua da usare per task e domande. potrebbero non coincidere'; builds on T065 (use-case Italian headings, --lang)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py,plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Read tasks/engine/T066-per-project-language-for-tasks-and-for-questions.md, do the open steps, run the Verification, update the task and the registry.
- short: Project languages

## Scope change 2026-10-27 (owner)

"le keyword possono restare in inglese, anzi, formalizziamole in inglese; poi eventualmente si fa interfaccia localizzabile".
Section headings (Goal, Steps, Verification, Log; question Context/Options/Recommendation/Answer; use-case sections) and
header field names are a formal ENGLISH vocabulary of the format, never translated. The language settings govern only
the CONTENT (prose of titles, goals, steps, questions) that sessions write. Localized display is a future UI concern.
Consequence for T065: use cases are generated with English headings again; the Italian heading aliases stay readable
for files already written that way (compatibility), and validate warns to normalize them.

## Goal

A project declares, in its versioned tasks tree, the language of its tasks and, separately, of its questions to the owner (they may differ), e.g. tasks in English and questions in Italian. Declared in the same place as extension fields (fenced toml in tasks/AGENTS.md, as T050): [tasks] language = "en", [questions] language = "it"; use cases follow the tasks language unless [use_cases] language is set; default en. One resolver replaces the regex in _detect_use_case_language (keep reading the old keys for compatibility, with a deprecation warning). Effects: the managed AGENTS.md block states both languages so every session writes accordingly; tasks new, questions ask and use-cases create use localized templates/headings where the engine has them (it, en); validate accepts the localized heading aliases; tasks show/config report the effective languages. Not machine-local config: languages are a project convention, versioned with tasks/.

## Steps

- [x] One resolver `resolve_project_languages` for project languages (`[tasks] language`, `[questions] language`, `[use_cases] language`, defaulting use cases to tasks language and overall default `en`) from `tasks/AGENTS.md` fenced `toml` block; BCP-47 validation with warning on empty/malformed values; compatibility with legacy T065 keys (`use_case_language`/`language` in `orchestration.toml` / `.ai-orchestration.local.toml`) with deprecation warning in `validate`; `tasks config` / `show-config` subcommands and `tasks show --json` language reporting.
- [x] Managed `AGENTS.md` block (`CANONICAL_TASKS_AGENTS_MD` / `build_managed_tasks_agents_block` / `render_upgraded_agents_md`) always states that section headings and header field names are fixed English keywords, and when languages are declared appends the effective content languages line (`Content language: tasks ..., questions ..., use cases ...`); documented in `task-pipeline/SKILL.md`.
- [x] Templates (`tasks new`, `questions ask`, `use-cases create`) always emit fixed English headings; `use-cases create --lang it` (and project `it` use-case language) keeps localized Italian default prose while emitting English headings; existing use-case files with Italian headings remain readable and `validate` warns `non-standard heading '<it>' (use '<en>')`.
- [x] Added unit tests in `test_tasks_engine.py` (`test_t066_project_languages_and_english_headings_keywords` and updated `test_t057_t061_t062_t063_t052_and_n064`) covering `it`/`it` declarations, byte-identical default outputs, `use-cases create --lang it` English headings + Italian prose + legacy Italian heading normalization warnings, legacy T065 key deprecation warning, and `config`/`show-config`.

## Verification

- [x] `~/.pyenv/shims/python3 -m pytest -q -p no:cacheprovider plugins/architect-side/skills/task-pipeline/scripts/` -> `233 passed`.
- [x] Scratch copy check of `/Users/Alfredo/works/dave_agent/tasks`: before changes `0 errors, 21 warnings`; after declaring `[tasks] language = "it"`, `[questions] language = "en"` in `AGENTS.md` fenced `toml`, `config` resolves `tasks=it, questions=en, use_cases=it` and `validate` has `0 errors, 21 warnings` (0 new warnings on English-headed files); on a use case with T065 Italian headings (`Descrizione`, `Precondizioni`, `Scenario`, `Comando di verifica`, `Criteri di accettazione`, `Registro delle verifiche`), `validate` emits `0 errors` and only the 6 normalization warnings (`non-standard heading '...' (use '...')`).

## Log (newest first)

- 2026-10-27, kilo: state `open` -> `delivered` — Implemented per-project content language resolver, fixed English keyword rules in AGENTS.md/SKILL.md, English headings on use-cases create with normalization warnings on legacy Italian headings, and `tasks config`/`show-config`.
