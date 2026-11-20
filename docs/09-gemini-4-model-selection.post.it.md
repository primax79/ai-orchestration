**Gemini 4: quale modello usare per gli agenti di coding (aggiornamento 20/11/2026)**

Dopo aver dormito un anno, Google ha cambiato la denominazione dei modelli Gemini. Adesso tira fuori un modello a settimana e si è inventata le varianti, ognuna con la sua fascia di costo. Per ora siamo a 4 modelli e una quindicina di varianti in totale, con funzionalità in parte sovrapposte. Ho fatto fare a Claude un mini studio, sia sulla documentazione ufficiale sia sui benchmark di terze parti, per capire cosa usare e quando.

I modelli sono **Argon** (13/10), **Carbon** (10/11), **Hydrogen** (12/11) e **Neon** (18/11). Ecco cosa usiamo da oggi nei task delegati a Kilo, e in generale:

🟢 **Lavoro di routine → `gemini-4-hydrogen`**
Implementazione, test, refactor meccanici, review di diff piccoli, esplorazione del codice.
È il modello che Google raccomanda come default ed è il successore ufficiale di 3.8 Flash. Costa $1.50 / $7.50 per milione di token (input/output), ha il free tier, è veloce (~165 tok/s). Su Terminal-Bench 4.1 fa 57% contro il 18% di 3.8 Flash (dato Google).

🟠 **Task complessi o rischiosi → `gemini-4-neon`**
Bug sottili, concorrenza, modifiche security-sensitive, spec, verifica indipendente, conflitti di merge non banali.
È il migliore sull'indice "coding agent" di Artificial Analysis (58.6). Costa $3 / $15 e richiede il piano a pagamento. Difetti: è prolisso e lento per task.

🔴 **Solo i problemi più difficili → `gemini-4-carbon`**
Architettura di sistema, audit di sicurezza, un bug su cui Neon si è bloccato.
Ha il ragionamento più forte, ma è il più lento e il più caro per task.

⚪ **Argon: di fatto superato, ma non ufficialmente.** Google non l'ha deprecato: è ancora "stable" e non c'è nessuna data di dismissione. Però l'ha già tolto dalla pagina "choosing a model", che consiglia solo Hydrogen, Neon e Carbon. In più, dal **1° dicembre** Argon raddoppia di prezzo ($4 / $20, come Carbon). A quel punto rende meno di Neon e costa di più, e Hydrogen in modalità `high` vale già quanto lui, a circa il 40% del costo per task. Non ha più senso sceglierlo.

⚪ **3.8 Flash:** il sostituto ufficiale è Hydrogen. Per token resta più economico fino al 31/12, poi costa uguale, ed è nettamente meno capace.

💰 **Costi** (USD per milione di token, listino standard Google AI Studio)

| Modello | Input | Output (thinking incluso) | Cache | Batch in / out | Free tier | Costo medio per task di coding agent¹ |
| --- | --- | --- | --- | --- | --- | --- |
| `gemini-4-hydrogen` | 1.50 | 7.50 | 0.075 | 0.75 / 3.75 | sì | ~$4.5 |
| `gemini-4-neon` | 3.00 | 15.00 | 0.15 | 1.50 / 7.50 | no | ~$6.9 |
| `gemini-4-carbon` | 2.00 → **4.00** dal 1/12 | 10.00 → **20.00** dal 1/12 | 0.10 → 0.20 | 1.00 / 5.00 → 2.00 / 10.00 | no | ~$9.8 |
| `gemini-4-argon` | 2.00 → **4.00** dal 1/12 | 10.00 → **20.00** dal 1/12 | 0.10 → 0.20 | come Carbon | no | ~$6.8 |
| `gemini-3.8-flash` | 0.75 → 1.50 dal 1/1/2027 | 3.75 → 7.50 dal 1/1/2027 | 0.075 → 0.15 | | sì | |
| `gemini-3.5-flash-lite` | 0.30 | 2.50 | 0.03 | 0.15 / 1.25 | sì | (solo testo: riassunti, estrazione) |

¹ Stima di Artificial Analysis (Coding Agent Index), quindi indipendente da Google, ripresa da Valyu. Conta più del listino, perché misura anche quanti token il modello spende davvero.

Velocità indicativa (Artificial Analysis): Hydrogen ~165 tok/s, Neon ~100, Argon ~66, Carbon ~56.

🚫 **Da non usare:** `gemini-3.1-pro*` e qualunque alias `-latest` (Google cambia il modello sottostante a ogni rilascio).

⚙️ **Il livello di thinking pesa più del listino.** Hydrogen e Neon partono di default da `high`, che produce molti token di ragionamento (fatturati come output). Impostatelo sempre in modo esplicito:
- `low` per esplorazione e domande sul codice
- `medium` per il lavoro di routine (`high` se tocca più file)
- `high` per i task complessi
- `xhigh` solo per i problemi davvero difficili, perché raddoppia circa i token

In Kilo: `kilo run --model google/gemini-4-hydrogen --variant medium "..."`

⚠️ **Avvertenza:** Hydrogen e Neon hanno pochi giorni di vita e quasi tutti i benchmark sono dichiarati da Google. Verificate l'output come fareste con qualunque esecutore, e segnalate i difetti che trovate, così correggiamo la scelta.

Fonti: [modelli](https://aistudio.google.com/docs/models), [scelta del modello](https://aistudio.google.com/docs/choosing-a-model) e [prezzi](https://aistudio.google.com/docs/pricing) di Google AI Studio; [Artificial Analysis](https://artificialanalysis.ai/models/gemini-4-neon); [model card di Hydrogen](https://deepmind.google/models/model-cards/gemini-4-hydrogen/).
