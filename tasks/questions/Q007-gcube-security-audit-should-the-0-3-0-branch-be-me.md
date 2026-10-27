# Q007 gcube-security-audit: il branch 0.3.0 deve essere unito e rilasciato così che il plugin diventi la copia canonica

- id: Q007
- question: gcube-security-audit: il branch 0.3.0 deve essere unito e rilasciato così che il plugin diventi la copia canonica?
- status: answered
- blocks: T019 (waiting)
- decider: owner
- asked-by: claude:orchestration
- asked: 2026-10-18
- origin-run: -
- open-answer: yes
- recommended: A
- short: Rilascio security-audit

## Context

La copia standalone (~/.kilo/skills/gcube-security-audit, con symlink in ~/.claude/skills) è alla versione 0.3.0: 21 file, metodo di audit a due livelli, 7 template di revisione, 7 guide di riferimento, 4 script aggiuntivi, rules.json più restrittivo. Il plugin (gcube-developer-tools 0.2.1) distribuisce ancora la 0.1.4. I file della 0.3.0 sono committati in gcube-ai-toolkit sul branch skills/security-audit-0.3-d4science-infra, mai unito in main. Dettagli: T019-skill-diffs.md sezione 2.

## Options

- **A** — Unire e rilasciare: fare merge del branch in main di gcube-ai-toolkit, incrementare la versione del plugin, aggiornare Claude, rimuovere la copia standalone e il symlink
- **B** — Standalone canonica: mantenere la copia standalone 0.3.0 e lasciare il plugin alla 0.1.4, riconosciuto nel Doctor
- **C** — Tornare alla 0.1.4: scartare il lavoro della 0.3.0 e mantenere solo la versione del plugin

## Answer

- choice: A
- answered-by: owner
- answered: 2026-10-18

```text
Owner 2026-10-18: recommended option A for all three (Q006-Q008).
```
