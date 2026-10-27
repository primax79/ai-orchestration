# Q009 Come chiudiamo le funzionalità consegnate che nessuna sessione utente utilizza e che quindi nessuno può validare tramite l'uso

- id: Q009
- question: Come chiudiamo le funzionalità consegnate che nessuna sessione utente utilizza e che quindi nessuno può validare tramite l'uso?
- status: answered
- blocks: -
- decider: owner
- asked-by: ai-coding-tools
- asked: 2026-10-21
- origin-run: -
- open-answer: no
- recommended: C

## Context

Regola dell'owner (2026-10-21): gli elementi consegnati vengono validati dalle sessioni che utilizzano gli strumenti. La prima campagna mostra che gcube-audit usa solo il motore dei task, kilo-mcp e la inbox, e ha risposto CANNOT VALIDATE per le run (07.5, 07.11), l'orchestratore headless (12.1, 12.5, 12.9), il Doctor (13.2, 13.3, 13.5, 13.7, T016), l'installazione delle skill di orchestrazione (T017, T018, T021) e il motore delle run e i trigger (T022, T026-T028). Gli elementi della web UI e di VS Code presentano lo stesso problema: le sessioni lavorano da terminale. Circa 40 dei 56 elementi consegnati potrebbero non avere alcun utente.

## Options

- **A** — Verifica dell'architetto: ai-coding-tools esegue un controllo live scriptato per elemento e lo chiude come 'done with a caveat: validated by the architect, no user yet'; un NOT OK di un utente lo riapre
- **B** — Mantenerli in stato delivered finché non compare un utente reale; l'indice li mostra come 'awaiting a user'
- **C** — L'owner valida tramite l'uso gli elementi UI e VS Code; opzione A per il resto
- **D** — Rivedere quali funzionalità inutilizzate mantenere: deprecare o congelare ciò che non serve a nessuna sessione (ad es. orchestratore headless, trigger) e validare solo ciò che resta

## Answer

- choice: C
- answered-by: owner
- answered: 2026-10-21
