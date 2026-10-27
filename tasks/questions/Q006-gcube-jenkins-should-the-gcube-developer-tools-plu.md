# Q006 gcube-jenkins: il plugin gcube-developer-tools deve diventare la copia canonica, portandovi gli esempi env

- id: Q006
- question: gcube-jenkins: il plugin gcube-developer-tools deve diventare la copia canonica, portandovi gli esempi env?
- status: answered
- blocks: T019 (in progress)
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-18
- origin-run: -
- open-answer: yes
- recommended: A
- short: Esempi env Jenkins

## Context

Esistono due copie. La copia standalone ~/.kilo/skills/gcube-jenkins contiene references/env/{java17,java8}.env.example, usati da gcube_credentials_check.sh; la copia del plugin (gcube-developer-tools@gcube-ai-toolkit 0.2.1) ne è priva perché la riga 254 'ENV/' di gcube-ai-toolkit/.gitignore ignora anche references/env su macOS. SKILL.md e gli script sono per il resto identici. Dettagli: tasks/env-doctor/notes/T019-skill-diffs.md sezione 1.

## Options

- **A** — Plugin canonico, portare gli esempi env: aggiungere references/env in whitelist in gcube-ai-toolkit/.gitignore, fare commit, incrementare la versione e aggiornare il plugin, ritirare la copia standalone
- **B** — Standalone canonica: mantenere ~/.kilo/skills/gcube-jenkins e segnare il duplicato come riconosciuto nel Doctor
- **C** — Plugin canonico così com'è: scartare gli esempi env e rimuovere la copia standalone

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-18

```text
Owner 2026-10-18: recommended option A for all three (Q006-Q008).
```
