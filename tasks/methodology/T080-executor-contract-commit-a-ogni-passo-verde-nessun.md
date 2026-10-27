# T080 executor-contract: commit a ogni passo verde, nessun segreto nei log, shell portabile su macOS/zsh

- id: T080
- title: executor-contract: commit a ogni passo verde, nessun segreto nei log, shell portabile su macOS/zsh
- category: methodology
- priority: P1
- priority-reason: Run interrotte perdono tutto il lavoro non committato; segreti stampati nei log (A.3, G.2, I.3, D.1)
- next-up: no
- state: open
- executor: kilo
- depends-on: -
- decider: -
- sources: lezioni di ricerca_auto 2026-10-17, analisi T078 (ai-orchestration/tasks/_reviews/2026-10-27-ricerca-auto-lessons-triage.md)
- paths: plugins/executor-side/skills/executor-contract/SKILL.template.md
- handoff: Read tasks/methodology/T080-executor-contract-commit-a-ogni-passo-verde-nessun.md, do the open steps, run the Verification, update the task and the registry.
- short: Contratto esecutore robusto

## Goal

Il contratto dell'esecutore (dal template, rigenerato) chiede un commit a ogni passo verde, vieta di stampare segreti trovati nell'ambiente o nei processi, indica forme shell portabili (zsh nomatch, sed -i su macOS) e la riga verification pending nel commit finale.

## Steps

- [ ] Template aggiornato, rigenerazione con --check, skill legata di kilo-mcp rigenerata

## Verification

- --check pulito; testo presente nelle copie generate
