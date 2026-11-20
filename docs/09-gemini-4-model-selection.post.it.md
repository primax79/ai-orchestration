**Gemini 4: quale modello usare per gli agenti di coding (aggiornamento 20/11/2026)**

Dopo aver dormito un anno, Google ha cambiato la denominazione dei modelli Gemini, tira fuori un modello a settimana e si è inventata le varianti, ognuna con la sua fascia di costo. Per ora siamo a 4 modelli e una quindicina di varianti in totale, con funzionalità in parte sovrapposte. Ho fatto fare a Claude un mini studio, sia sulla documentazione ufficiale sia sui benchmark di terze parti, per capire cosa usare e quando.

I modelli sono **Argon** (13/10), **Carbon** (10/11), **Hydrogen** (12/11) e **Neon** (18/11). Ecco cosa uso da oggi nei task delegati a Kilo, e in generale:

🟢 **Lavoro di routine → `gemini-4-hydrogen`**
Implementazione, test, refactor meccanici, review di diff piccoli, esplorazione del codice.
Ragionamento: `medium` di default, `high` se il task tocca più file, `low` per esplorazione e domande sul codice. Livelli disponibili: low, medium, high, xhigh. Se non lo imposti, parte da `high`.
È il modello che Google raccomanda come default ed è il successore ufficiale di 3.8 Flash. Costa $1.50 / $7.50 per milione di token (input/output), ha il free tier, è veloce (~165 tok/s). Su Terminal-Bench 4.1 fa 57% contro il 18% di 3.8 Flash (dato Google).
Equivalenti: **Claude Sonnet 5.5** (`claude-sonnet-5-5`, $2 / $10), effort `medium` per il coding agentico e `low` per l'esplorazione; parte da `high` se non lo imposti. **OpenAI GPT-6.2 Sol** (`gpt-6.2-sol`, $2 / $10), oppure **GPT-6.1 Terra** (`gpt-6.1-terra`, $1 / $5) se conta il costo.

| Modello | Costo in / out (USD per 1M token) | Velocità (token/s) |
| --- | --- | --- |
| Gemini 4 Hydrogen | 1.50 / 7.50 | ~165 |
| Claude Sonnet 5.5 | 2 / 10 | ~130-155 |
| GPT-6.2 Sol | 2 / 10 | ~65⁴ |
| GPT-6.1 Terra | 1 / 5 | n.d. |

🟠 **Task complessi o rischiosi → `gemini-4-neon`**
Bug sottili, concorrenza, modifiche security-sensitive, spec, verifica indipendente, conflitti di merge non banali.
Ragionamento: `high`. `medium` basta per i turni di orchestrazione (dispatch, attese, bookkeeping). `xhigh` solo se `high` non basta, perché circa raddoppia i token. Livelli disponibili: low, medium, high, xhigh. Se non lo imposti, parte da `high`.
È il migliore sull'indice "coding agent" di Artificial Analysis (58.6). Costa $3 / $15 e richiede il piano a pagamento. Difetti: è prolisso e lento per task.
Equivalenti: **Claude Opus 5.5** (`claude-opus-5-5`, $4 / $20), effort `high`. Va impostato esplicitamente, perché su Opus 5.5 il default è `medium`. **OpenAI GPT-6.2 Astra** (`gpt-6.2-astra`, $8 / $40), oppure GPT-6.2 Sol con effort alto. OpenAI non ha un modello GPT-6.x in questa fascia di prezzo.

| Modello | Costo in / out (USD per 1M token) | Velocità (token/s) |
| --- | --- | --- |
| Gemini 4 Neon | 3 / 15 | ~100 |
| Claude Opus 5.5 | 4 / 20 | ~95-105 |
| GPT-6.2 Astra | 8 / 40 | ~63⁴ |
| GPT-6.2 Sol, effort alto | 2 / 10 | ~65⁴ |

🔴 **Solo i problemi più difficili → `gemini-4-carbon`**
Architettura di sistema, audit di sicurezza, un bug su cui Neon si è bloccato.
Ragionamento: `high`, che è anche il massimo (livelli disponibili: low, medium, high). Se non lo imposti, parte da `medium`.
Ha il ragionamento più forte, ma è il più lento e il più caro per task.
Equivalenti: **Claude Fable 5.2** (`claude-fable-5-2`, $8 / $40), effort `high`; `xhigh` e `max` solo dove il guadagno è misurato. **OpenAI GPT-6.2 Astra** (`gpt-6.2-astra`, $8 / $40), con effort al massimo.

| Modello | Costo in / out (USD per 1M token) | Velocità (token/s) |
| --- | --- | --- |
| Gemini 4 Carbon | 2 / 10, dal 1/12 4 / 20 | ~56 |
| Claude Fable 5.2 | 8 / 40 | ~92 |
| GPT-6.2 Astra | 8 / 40 | ~63⁴ |

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

🔁 **Gli equivalenti Claude e OpenAI**, per chi usa Claude Code o Codex (USD per milione di token, input / output, listini ufficiali)

| Uso | Gemini | Claude | OpenAI |
| --- | --- | --- | --- |
| Problemi più difficili | `gemini-4-carbon`: 2 / 10, poi 4 / 20 dal 1/12 | `claude-fable-5-2`: 8 / 40 | `gpt-6.2-astra`: 8 / 40 |
| Task complessi | `gemini-4-neon`: 3 / 15 | `claude-opus-5-5`: 4 / 20 | `gpt-6.2-astra` (8 / 40) oppure `gpt-6.2-sol` con effort alto (2 / 10)² |
| Routine, coding quotidiano, agenti in parallelo | `gemini-4-hydrogen`: 1.50 / 7.50 | `claude-sonnet-5-5`: 2 / 10 | `gpt-6.2-sol`: 2 / 10 oppure `gpt-6.1-terra`: 1 / 5 |
| Testo in volume: riassunti, estrazione, classificazione | `gemini-3.5-flash-lite`: 0.30 / 2.50 | `claude-haiku-5-5`: 0.10 / 0.50³ | `gpt-6-luna`: 0.10 / 0.50 |

Cache in lettura: Claude ha 0.20 su Fable e Opus e 0.10 su Sonnet; OpenAI ha 0.40 su Astra, 0.10 su Sol, 0.05 su Terra e 0.01 su Luna. Il Batch costa il 50% in tutti e tre i casi.

² OpenAI non ha un modello GPT-6.x a metà tra Sol e Astra (il vecchio `gpt-5.6-sol` costa 4 / 20). Anche Claude e OpenAI regolano la profondità di ragionamento con un "effort" (`low` … `max`), che pesa sul costo quanto il modello.
³ Haiku 5.5 costa così fino a 100K token di prompt; oltre, 0.50 / 2.50.

Attenzione: le corrispondenze sono **per fascia di prezzo e di posizionamento**, non misurate da noi sugli stessi task. A parità di riga i modelli non si equivalgono.

🚫 **Da non usare:** `gemini-3.1-pro*` e qualunque alias `-latest` (Google cambia il modello sottostante a ogni rilascio).

⚙️ **Il livello di thinking pesa più del listino.** Hydrogen e Neon partono di default da `high`, che produce molti token di ragionamento (fatturati come output). Impostatelo sempre in modo esplicito:
- `low` per esplorazione e domande sul codice
- `medium` per il lavoro di routine (`high` se tocca più file)
- `high` per i task complessi
- `xhigh` solo per i problemi davvero difficili, perché raddoppia circa i token

In Kilo: `kilo run --model google/gemini-4-hydrogen --variant medium "..."`

⚠️ **Avvertenza:** Hydrogen e Neon hanno pochi giorni di vita e quasi tutti i benchmark sono dichiarati da Google. Verificate l'output come fareste con qualunque esecutore, e segnalate i difetti che trovate, così correggiamo la scelta.

Velocità nelle tabelle: quelle di Gemini vengono da Artificial Analysis. Quelle di Claude e OpenAI vengono da articoli che citano Artificial Analysis, con livelli di effort diversi: prendetele come ordine di grandezza.
⁴ Misurate su GPT-6 Astra e GPT-6.1 Sol. Per GPT-6.2 e Terra non ho trovato misure.

Fonti: [prezzi OpenAI](https://developers.openai.com/api/docs/pricing); [prezzi Claude](https://www.anthropic.com/pricing); [modelli](https://aistudio.google.com/docs/models), [scelta del modello](https://aistudio.google.com/docs/choosing-a-model) e [prezzi](https://aistudio.google.com/docs/pricing) di Google AI Studio; [Artificial Analysis](https://artificialanalysis.ai/models/gemini-4-neon); [model card di Hydrogen](https://deepmind.google/models/model-cards/gemini-4-hydrogen/).
