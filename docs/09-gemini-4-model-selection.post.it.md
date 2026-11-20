**Gemini 4: quale modello usare per gli agenti di coding (aggiornamento 20/11/2026)**

Google ha completato la famiglia Gemini 4: **Hydrogen** (12/11), **Carbon** (10/11), **Neon** (18/11), oltre ad **Argon** di ottobre. Ho letto la documentazione ufficiale di AI Studio e le analisi indipendenti (Artificial Analysis e altre). Ecco cosa usiamo da oggi nei task delegati a Kilo e in generale:

🟢 **Lavoro di routine → `gemini-4-hydrogen`**
Implementazione, test, refactor meccanici, review di diff piccoli, esplorazione del codice.
È il modello che Google raccomanda come default ed è il successore ufficiale di 3.8 Flash. Costa $1.50 / $7.50 per milione di token (input/output), ha il free tier, è veloce (~165 tok/s). Su Terminal-Bench 4.1 fa 57% contro il 18% di 3.8 Flash (dato Google).

🟠 **Task complessi o rischiosi → `gemini-4-neon`**
Bug sottili, concorrenza, modifiche security-sensitive, spec, verifica indipendente, conflitti di merge non banali.
È il migliore sull'indice "coding agent" di Artificial Analysis (58.6). Costa $3 / $15 e richiede il piano a pagamento. Difetti: è prolisso e lento per task.

🔴 **Solo i problemi più difficili → `gemini-4-carbon`**
Architettura di sistema, audit di sicurezza, un bug su cui Neon si è bloccato.
Ha il ragionamento più forte, ma è il più lento e il più caro per task.

⚪ **Argon e 3.8 Flash: non più come default.** Dal **1° dicembre** Argon raddoppia ($4 / $20, come Carbon), mentre Neon costa meno e rende di più. Hydrogen in modalità `high` vale già quanto Argon, a circa il 40% del costo per task. 3.8 Flash resta più economico per token fino al 31/12, ma è nettamente meno capace.

🚫 **Da non usare:** `gemini-3.1-pro*` e qualunque alias `-latest` (Google cambia il modello sottostante a ogni rilascio).

⚙️ **Il livello di thinking pesa più del listino.** Hydrogen e Neon partono di default da `high`, che produce molti token di ragionamento (fatturati come output). Impostatelo sempre in modo esplicito:
- `low` per esplorazione e domande sul codice
- `medium` per il lavoro di routine (`high` se tocca più file)
- `high` per i task complessi
- `xhigh` solo per i problemi davvero difficili, perché raddoppia circa i token

In Kilo: `kilo run --model google/gemini-4-hydrogen --variant medium "..."`

⚠️ **Avvertenza:** Hydrogen e Neon hanno pochi giorni di vita e quasi tutti i benchmark sono dichiarati da Google. Verificate l'output come fareste con qualunque esecutore, e segnalate i difetti che trovate, così correggiamo la scelta.

Fonti: [modelli](https://aistudio.google.com/docs/models), [scelta del modello](https://aistudio.google.com/docs/choosing-a-model) e [prezzi](https://aistudio.google.com/docs/pricing) di Google AI Studio; [Artificial Analysis](https://artificialanalysis.ai/models/gemini-4-neon); [model card di Hydrogen](https://deepmind.google/models/model-cards/gemini-4-hydrogen/).
