# T034 Feedback sugli strumenti integrato nel prodotto: ai-orch feedback, regola nelle skill, upgrade di AGENTS.md

- id: T034
- title: Feedback sugli strumenti integrato nel prodotto: ai-orch feedback, regola nelle skill, upgrade di AGENTS.md
- category: server-and-bindings
- priority: P1
- priority-reason: Owner 2026-10-21: ogni sessione che utilizza gli strumenti deve segnalare esigenze e miglioramenti; la regola deve risiedere nel prodotto, non nei messaggi
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: owner request 2026-10-21; inbox N001-N024 (first feedback round)
- paths: bin/ai-orch, plugins/architect-side/skills/task-pipeline/scripts/tasks_engine.py, plugins/*/skills/*/SKILL.template.md, bindings
- handoff: Leggere tasks/server-and-bindings/T034-tooling-feedback-built-into-the-product-ai-orch-fe.md, eseguire i passaggi aperti, lanciare la Verification, aggiornare il task e il registro.
- verifier: gcube-atlas-83
- use-cases: UC021
- short: Canale feedback integrato

## Goal

Una sessione in qualsiasi workspace segnala un'esigenza, un difetto o un miglioramento relativo agli strumenti con un unico comando (ai-orch feedback), che atterra come nota nella inbox dell'albero tasks del progetto ai-orchestration ovunque lo strumento sia installato; le skill generate e il file AGENTS.md scritto da upgrade istruiscono ogni sessione a farlo, e i maintainer smistano le note trasformandole in task.

## Steps
- [x] Implementato secondo le specifiche e l'obiettivo del task.
## Verification
- [x] Verificato tramite suite di test automatizzata e controlli di validazione.
