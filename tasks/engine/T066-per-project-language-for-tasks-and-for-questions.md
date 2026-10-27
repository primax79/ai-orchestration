# T066 Per-project language for tasks and for questions

- id: T066
- title: Per-project language for tasks and for questions
- category: engine
- priority: P2
- priority-reason: Owner request 2026-10-27; projects write tasks in one language and ask the owner in another (dave_agent: Italian tasks)
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: owner 2026-10-27: 'prevediamo una configurazione, per progetto, della lingua da usare per task e domande. potrebbero non coincidere'; builds on T065 (use-case Italian headings, --lang)
- paths: plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py,plugins/architect-side/skills/task-pipeline/SKILL.md
- handoff: Read tasks/engine/T066-per-project-language-for-tasks-and-for-questions.md, do the open steps, run the Verification, update the task and the registry.
- short: Project languages

## Goal

A project declares, in its versioned tasks tree, the language of its tasks and, separately, of its questions to the owner (they may differ), e.g. tasks in English and questions in Italian. Declared in the same place as extension fields (fenced toml in tasks/AGENTS.md, as T050): [tasks] language = "en", [questions] language = "it"; use cases follow the tasks language unless [use_cases] language is set; default en. One resolver replaces the regex in _detect_use_case_language (keep reading the old keys for compatibility, with a deprecation warning). Effects: the managed AGENTS.md block states both languages so every session writes accordingly; tasks new, questions ask and use-cases create use localized templates/headings where the engine has them (it, en); validate accepts the localized heading aliases; tasks show/config report the effective languages. Not machine-local config: languages are a project convention, versioned with tasks/.

## Steps

- [ ] One resolver for project languages (tasks, questions, use cases) from tasks/AGENTS.md fenced toml; compatibility with orchestration.toml/.ai-orchestration.local.toml keys used by T065
- [ ] Managed AGENTS.md block states the languages; upgrade/sync writes them
- [ ] Localized templates for questions ask and tasks new (it/en), headings aliases accepted by validate and parsers
- [ ] Tests: tasks en + questions it in one project; default en; old key still read with warning

## Verification

- Tests above green; on a scratch copy of dave_agent tasks/: declare tasks it, questions en; tasks new and questions ask produce the right language; validate clean
