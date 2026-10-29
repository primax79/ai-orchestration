# N085 inbox resolve rimuove il campo short dalla nota

- id: N085
- title: inbox resolve rimuove il campo short dalla nota
- kind: bug
- status: ready
- created: 2026-10-29T22:37:09.374230+00:00
- author: ai-coding-tools
- about: -
- produced: -
- processed-by: -
- short: inbox resolve rimuove campo

ai-orch inbox resolve N078 --produced ... --by ... (2026-10-29) sposta la nota in analyzed/ e aggiorna status/produced/processed-by, ma cancella la riga '- short: ...' dall'header (verificato con diff tra la copia originale e quella risolta per N078, N079, N083). Atteso: short conservato, perche' serve per citare la nota.

---
- Author: ai-coding-tools
- Workspace: /Users/Alfredo/works/ai-coding-tools
- ai-orch: 1.1.0 (2965604)
- Date: 2026-10-29 22:37:09 UTC
