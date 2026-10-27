# T015 Le etichette della navbar vanno a capo su larghezze ridotte

- id: T015
- title: Le etichette della navbar vanno a capo su larghezze ridotte
- category: micro
- priority: P3
- priority-reason: Cosmetico, ma il Simple Browser di VS Code e i pannelli laterali sono stretti di default
- next-up: no
- state: done
- executor: kilo
- depends-on: -
- decider: -
- sources: owner screenshot in the VS Code Simple Browser (2026-10-17)
- paths: ../ai-orchestration-ui/frontend/src/components/Navbar.tsx
- handoff: Leggere tasks/micro/T015-navbar-narrow-width.md e correggere il problema.
- short: A capo etichette navbar

## Goal

A larghezze inferiori a circa 1100 px, gli elementi della navbar ("Install Skills & MCP", "Environment Doctor", "Orchestrator Config") vanno a capo su due o tre righe e il chip del workspace viene tagliato. La navbar deve rimanere su una sola riga: etichette brevi o elementi con sola icona e tooltip sotto un breakpoint, e uno scorrimento orizzontale o menu di overflow come ultima risorsa.

## Steps

1. Aggiungere `white-space: nowrap` agli elementi e usare etichette brevi ("Install", "Doctor", "Config") sotto 1100 px.
2. Usare elementi con sola icona e tooltip `title` sotto 760 px.
3. Mantenere visibili i badge (conteggio Decisions, run attive) in ogni modalità.

## Verification

Con Playwright MCP a 1400, 1000 e 700 px di larghezza, la navbar è alta una sola riga, nessuna etichetta va a capo e i badge sono visibili.
